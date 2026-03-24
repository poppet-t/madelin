//! Sequence level mutation.
use super::{foreach_call_arg_mut, restore_partial_ctx, restore_res_ctx};
use crate::{
    bridge_bias::{protected_structural_len, syscall_bias_multiplier},
    context::Context,
    corpus::CorpusWrapper,
    gen::{gen_one_call, prog_len_range},
    lang_mod::mutate::select_call_to_wrapper,
    prog::{Call, Prog},
    select::select_with_calls,
    syscall::SyscallId,
    value::ResValueKind,
    HashMap, RngType,
};
use rand::prelude::*;

fn insertion_start(protected_len: usize, call_count: usize) -> usize {
    protected_len.min(call_count)
}

fn removable_call_range(protected_len: usize, call_count: usize) -> Option<std::ops::Range<usize>> {
    let protected_len = protected_len.min(call_count);
    (protected_len < call_count).then_some(protected_len..call_count)
}

fn protected_call_boundary(ctx: &Context<'_, '_>) -> usize {
    protected_structural_len(ctx.target(), ctx.calls())
}

/// Select a prog from `corpus` and splice it with calls in the `ctx` randomly.
pub fn splice(ctx: &mut Context, corpus: &CorpusWrapper, rng: &mut RngType) -> (bool, usize) {
    if ctx.calls.is_empty() || ctx.calls.len() > prog_len_range().end || corpus.is_empty() {
        return (false, 99);
    }

    let p = corpus.select_one(rng).unwrap();
    let mut calls = p.calls;
    // mapping resource id of `calls`, continue with current `ctx.next_res_id`
    mapping_res_id(ctx, &mut calls);
    restore_partial_ctx(ctx, &calls);
    let idx = rng.gen_range(insertion_start(protected_call_boundary(ctx), ctx.calls.len())..=ctx.calls.len());
    debug_info!(
        "splice: splicing {} call(s) to location {}",
        calls.len(),
        idx
    );
    ctx.calls.splice(idx..idx, calls);
    (true, 3)
}

/// Insert calls to random location of ctx's calls.
pub fn insert_calls(
    ctx: &mut Context,
    _corpus: &CorpusWrapper,
    rng: &mut RngType,
) -> (bool, usize) {
    if ctx.calls.len() > prog_len_range().end {
        return (false, 99);
    }

    let idx = rng.gen_range(insertion_start(protected_call_boundary(ctx), ctx.calls.len())..=ctx.calls.len());
    restore_res_ctx(ctx, idx); // restore the resource information before call `idx`
    let (sid, op) = select_call_to_wrapper(ctx, rng, idx);
    debug_info!(
        "insert_calls: inserting {} to location {}",
        ctx.target.syscall_of(sid).name(),
        idx
    );
    let mut calls_backup = std::mem::take(&mut ctx.calls);
    gen_one_call(ctx, rng, sid);
    let new_calls = std::mem::take(&mut ctx.calls);
    debug_info!("insert_calls: {} call(s) inserted", new_calls.len());
    calls_backup.splice(idx..idx, new_calls);
    ctx.calls = calls_backup;
    (true, op)
}

pub fn remove_call(ctx: &mut Context, _corpus: &CorpusWrapper, rng: &mut RngType) -> (bool, usize) {
    let Some(removable) = removable_call_range(protected_call_boundary(ctx), ctx.calls.len()) else {
        return (false, 99);
    };

    let idx = rng.gen_range(removable);
    let calls = std::mem::take(&mut ctx.calls);
    let mut p = Prog::new(calls);
    debug_info!("remove_call: removing call-{}", idx);
    p.remove_call_inplace(idx);
    ctx.calls = p.calls;
    (true, 4)
}

/// Select new call to location `idx`.
pub fn select_call_to(ctx: &mut Context, rng: &mut RngType, idx: usize) -> SyscallId {
    let mut candidates: HashMap<SyscallId, u64> = HashMap::new();
    let r = ctx.relation().inner.read().unwrap();
    let calls = ctx.calls();

    // first, consider calls that can be influenced by calls before `idx`.
    for sid in calls[..idx].iter().map(|c| c.sid()) {
        for candidate in r.influence_of(sid).iter().copied() {
            let entry = candidates.entry(candidate).or_default();
            *entry += 1;
        }
    }

    // then, consider calls that can be influence calls after `idx`.
    if idx != calls.len() {
        for sid in calls[idx..].iter().map(|c| c.sid()) {
            for candidate in r.influence_by_of(sid).iter().copied() {
                let entry = candidates.entry(candidate).or_default();
                *entry += 1;
            }
        }
    }

    let candidates: Vec<(SyscallId, u64)> = candidates
        .into_iter()
        .map(|(sid, weight)| (sid, weight * syscall_bias_multiplier(ctx.target(), sid)))
        .collect();
    if let Ok(candidate) = candidates.choose_weighted(rng, |candidate| candidate.1) {
        candidate.0
    } else {
        // failed to select with relation, use normal strategy.
        select_with_calls(ctx, rng)
    }
}

/// Mapping resource id of `calls`, make sure all `res_id` in `calls` is bigger then current `next_res_id`
fn mapping_res_id(ctx: &mut Context, calls: &mut [Call]) {
    for call in calls {
        foreach_call_arg_mut(call, |val| {
            if let Some(val) = val.as_res_mut() {
                match &mut val.kind {
                    ResValueKind::Ref(id) | ResValueKind::Own(id) => *id += ctx.next_res_id,
                    ResValueKind::Null => (),
                }
            }
        });
        for ids in call.generated_res.values_mut() {
            for id in ids {
                *id += ctx.next_res_id;
            }
        }
        for ids in call.used_res.values_mut() {
            for id in ids {
                *id += ctx.next_res_id;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{insertion_start, removable_call_range, remove_call, splice};
    use crate::{
        bridge_bias::{set_bridge_bias, BridgeBiasConfig},
        context::Context,
        corpus::CorpusWrapper,
        prog::{CallBuilder, Prog},
    };
    use rand::{rngs::SmallRng, SeedableRng};
    use std::sync::{Mutex, OnceLock};

    fn bias_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    fn call_ids(ctx: &Context<'_, '_>) -> Vec<usize> {
        ctx.calls().iter().map(|call| call.sid()).collect()
    }

    #[test]
    fn insertion_start_clamps_to_call_count() {
        let _guard = bias_lock().lock().unwrap();
        set_bridge_bias(None);

        assert_eq!(insertion_start(3, 6), 3);
        assert_eq!(insertion_start(3, 2), 2);
    }

    #[test]
    fn removable_call_range_skips_protected_prefix() {
        let _guard = bias_lock().lock().unwrap();
        set_bridge_bias(None);

        assert_eq!(removable_call_range(3, 6), Some(3..6));
        assert_eq!(removable_call_range(3, 3), None);
    }

    #[test]
    fn remove_call_never_deletes_protected_prefix() {
        let _guard = bias_lock().lock().unwrap();
        set_bridge_bias(Some(BridgeBiasConfig {
            preserve_prefix_len: 3,
            ..BridgeBiasConfig::default()
        }));

        let mut ctx = Context::dummy();
        ctx.calls = vec![
            CallBuilder::new(0).build(),
            CallBuilder::new(1).build(),
            CallBuilder::new(2).build(),
            CallBuilder::new(3).build(),
        ];

        let mut rng = SmallRng::seed_from_u64(1);
        let (mutated, op) = remove_call(&mut ctx, &CorpusWrapper::new(), &mut rng);

        assert!(mutated);
        assert_eq!(op, 4);
        assert_eq!(call_ids(&ctx), vec![0, 1, 2]);

        set_bridge_bias(None);
    }

    #[test]
    fn splice_inserts_after_protected_prefix() {
        let _guard = bias_lock().lock().unwrap();
        set_bridge_bias(Some(BridgeBiasConfig {
            preserve_prefix_len: 3,
            ..BridgeBiasConfig::default()
        }));

        let mut ctx = Context::dummy();
        ctx.calls = vec![
            CallBuilder::new(0).build(),
            CallBuilder::new(1).build(),
            CallBuilder::new(2).build(),
            CallBuilder::new(3).build(),
        ];

        let corpus = CorpusWrapper::new();
        corpus.add_prog(Prog::new(vec![CallBuilder::new(10).build()]), 1);

        let mut rng = SmallRng::seed_from_u64(7);
        let (mutated, op) = splice(&mut ctx, &corpus, &mut rng);

        assert!(mutated);
        assert_eq!(op, 3);
        assert_eq!(call_ids(&ctx)[..3], [0, 1, 2]);
        assert_eq!(ctx.calls().len(), 5);

        set_bridge_bias(None);
    }
}

use crate::config::Config;
use healer_core::bridge_bias::load_bridge_bias;
use serde::Serialize;
use std::{fs::{read_dir, read_to_string}, path::{Path, PathBuf}};

#[derive(Debug, Serialize)]
pub struct RunDebugSummary {
    pub target: String,
    pub kernel_image: Option<String>,
    pub disk_image: String,
    pub syz_dir: String,
    pub syz_executor: String,
    pub output_dir: String,
    pub seeded: bool,
    pub input_dir: Option<String>,
    pub input_seed_program_count: usize,
    pub relations_file: Option<String>,
    pub relation_edge_count: usize,
    pub bridge_bias_path: Option<String>,
    pub bridge_bias_loaded: bool,
    pub focus_syscall_families: Vec<String>,
    pub preserve_prefix_len: Option<usize>,
    pub prefer_two_thread_schedule: Option<bool>,
    pub prefer_collide: Option<bool>,
}

fn count_input_programs(path: &Path) -> usize {
    read_dir(path)
        .ok()
        .into_iter()
        .flat_map(|iter| iter.filter_map(Result::ok))
        .filter(|entry| entry.path().is_file())
        .count()
}

fn count_relation_edges(path: &Path) -> usize {
    read_to_string(path)
        .ok()
        .map(|content| {
            content
                .lines()
                .map(str::trim)
                .filter(|line| !line.is_empty())
                .count()
        })
        .unwrap_or(0)
}

pub fn build_debug_summary(config: &Config) -> anyhow::Result<RunDebugSummary> {
    let input_dir = config.input.as_ref().map(|p| p.display().to_string());
    let input_seed_program_count = config.input.as_ref().map(|p| count_input_programs(p)).unwrap_or(0);
    let relations_file = config.relations.as_ref().map(|p| p.display().to_string());
    let relation_edge_count = config.relations.as_ref().map(|p| count_relation_edges(p)).unwrap_or(0);

    let mut focus_syscall_families = Vec::new();
    let mut preserve_prefix_len = None;
    let mut prefer_two_thread_schedule = None;
    let mut prefer_collide = None;
    let mut bridge_bias_loaded = false;
    let bridge_bias_path = config.bridge_bias.as_ref().map(PathBuf::from);

    if let Some(path) = bridge_bias_path.as_ref() {
        let bias = load_bridge_bias(path)?;
        bridge_bias_loaded = true;
        focus_syscall_families = bias.focus_syscall_families;
        preserve_prefix_len = Some(bias.preserve_prefix_len);
        prefer_two_thread_schedule = Some(bias.prefer_two_thread_schedule);
        prefer_collide = Some(bias.prefer_collide);
    }

    Ok(RunDebugSummary {
        target: format!("{}/{}", config.os, config.arch),
        kernel_image: config.qemu_config.kernel_img.clone(),
        disk_image: config.qemu_config.disk_img.clone(),
        syz_dir: config.syz_dir.display().to_string(),
        syz_executor: config.syz_executor().display().to_string(),
        output_dir: config.output.display().to_string(),
        seeded: config.input.is_some() || config.relations.is_some() || config.bridge_bias.is_some(),
        input_dir,
        input_seed_program_count,
        relations_file,
        relation_edge_count,
        bridge_bias_path: config.bridge_bias.as_ref().map(|p| p.display().to_string()),
        bridge_bias_loaded,
        focus_syscall_families,
        preserve_prefix_len,
        prefer_two_thread_schedule,
        prefer_collide,
    })
}

pub fn render_debug_summary(summary: &RunDebugSummary) -> String {
    let mut lines = Vec::new();
    lines.push(format!("target: {}", summary.target));
    lines.push(format!("kernel_image: {}", summary.kernel_image.clone().unwrap_or_else(|| "<none>".to_string())));
    lines.push(format!("disk_image: {}", summary.disk_image));
    lines.push(format!("syz_dir: {}", summary.syz_dir));
    lines.push(format!("syz_executor: {}", summary.syz_executor));
    lines.push(format!("output_dir: {}", summary.output_dir));
    lines.push(format!("seeded: {}", summary.seeded));
    lines.push(format!("input_dir: {}", summary.input_dir.clone().unwrap_or_else(|| "<none>".to_string())));
    lines.push(format!("input_seed_program_count: {}", summary.input_seed_program_count));
    lines.push(format!("relations_file: {}", summary.relations_file.clone().unwrap_or_else(|| "<none>".to_string())));
    lines.push(format!("relation_edge_count: {}", summary.relation_edge_count));
    lines.push(format!("bridge_bias_path: {}", summary.bridge_bias_path.clone().unwrap_or_else(|| "<none>".to_string())));
    lines.push(format!("bridge_bias_loaded: {}", summary.bridge_bias_loaded));
    lines.push(format!("focus_syscall_families: {}", if summary.focus_syscall_families.is_empty() { "<none>".to_string() } else { summary.focus_syscall_families.join(", ") }));
    lines.push(format!("preserve_prefix_len: {}", summary.preserve_prefix_len.map(|v| v.to_string()).unwrap_or_else(|| "<none>".to_string())));
    lines.push(format!("prefer_two_thread_schedule: {}", summary.prefer_two_thread_schedule.map(|v| v.to_string()).unwrap_or_else(|| "<none>".to_string())));
    lines.push(format!("prefer_collide: {}", summary.prefer_collide.map(|v| v.to_string()).unwrap_or_else(|| "<none>".to_string())));
    lines.join("\n") + "\n"
}

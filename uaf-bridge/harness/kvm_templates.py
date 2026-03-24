from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Any


SUPPORTED_LOC0_FUNCTION = "kvm_timer_vcpu_terminate"
SUPPORTED_LOC1_FUNCTION = "kvm_timer_should_fire"
SUPPORTED_ENTRY_FUNCTION = "kvm_vcpu_ioctl"
SUPPORTED_OBJECT_HINT = "kvm_vcpu_arch_timer"
SUPPORTED_FAMILY_ID = "kvm_arm64_timer_close_vs_run"


@dataclass(frozen=True)
class HarnessTemplateContext:
    candidate_id: str
    family_id: str
    entry_function: str
    free_function: str
    free_file: str
    free_line: int
    use_function: str
    use_file: str
    use_line: int
    free_thread_id: int
    use_thread_id: int
    free_timestamp: int
    use_timestamp: int
    timing_applies_to: str


def _unsupported_harness_candidate(reason: str) -> ValueError:
    return ValueError(f"unsupported harness candidate family: {reason}")


def _event_record(plan: dict[str, Any], event_name: str) -> dict[str, int]:
    ordered_steps = plan.get("ordered_steps")
    if not isinstance(ordered_steps, list):
        raise ValueError("witness plan has no ordered_steps array")
    for step in ordered_steps:
        if isinstance(step, dict) and step.get("event") == event_name:
            return {
                "step_index": int(step.get("step_index", -1)),
                "timestamp": int(step.get("timestamp", -1)),
            }
    raise ValueError(f"witness plan is missing event {event_name}")


def _thread_id_for_event(plan: dict[str, Any], event_name: str) -> int:
    threads = plan.get("threads")
    if not isinstance(threads, list):
        raise ValueError("witness plan has no threads array")
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        thread_id = thread.get("thread_id")
        steps = thread.get("steps")
        if not isinstance(thread_id, int) or not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict) and step.get("event") == event_name:
                return thread_id
    raise ValueError(f"witness plan has no thread assignment for event {event_name}")


def _loc(payload: dict[str, Any], key: str) -> dict[str, Any]:
    location = payload.get(key)
    if isinstance(location, dict):
        return location
    raise ValueError(f"candidate is missing {key}")


def _has_supported_entry(candidate: dict[str, Any]) -> bool:
    entries = candidate.get("entries")
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if isinstance(entry, dict) and entry.get("entry_func") == SUPPORTED_ENTRY_FUNCTION:
            return True
    return False


def _object_hint_text(candidate: dict[str, Any]) -> str:
    raw_warning = candidate.get("raw_warning")
    if isinstance(raw_warning, dict):
        object_hints = raw_warning.get("object_hints")
        if isinstance(object_hints, dict) and isinstance(object_hints.get("object_type"), str):
            return object_hints["object_type"]
    return ""


def build_kvm_timer_context(candidate: dict[str, Any], plan: dict[str, Any]) -> HarnessTemplateContext:
    analysis_context = candidate.get("analysis_context")
    if not isinstance(analysis_context, dict) or analysis_context.get("subsystem") != "kvm":
        raise _unsupported_harness_candidate("micro-harness support is limited to KVM candidates")
    if candidate.get("flow") != "Con":
        raise _unsupported_harness_candidate("micro-harness support currently requires concurrent KVM candidates")
    if not _has_supported_entry(candidate):
        raise _unsupported_harness_candidate(
            f"micro-harness support currently requires entry function {SUPPORTED_ENTRY_FUNCTION}"
        )

    loc0 = _loc(candidate, "loc0")
    loc1 = _loc(candidate, "loc1")
    if loc0.get("function") != SUPPORTED_LOC0_FUNCTION or loc1.get("function") != SUPPORTED_LOC1_FUNCTION:
        raise _unsupported_harness_candidate(
            "micro-harness support currently only covers the arm64 KVM timer close-vs-run family"
        )

    object_hint_text = _object_hint_text(candidate)
    if SUPPORTED_OBJECT_HINT not in object_hint_text:
        raise _unsupported_harness_candidate(
            "micro-harness support currently requires the timer object hint from the narrow KVM candidate family"
        )

    free_step = _event_record(plan, "free")
    use_step = _event_record(plan, "use")
    free_thread_id = _thread_id_for_event(plan, "free")
    use_thread_id = _thread_id_for_event(plan, "use")
    if free_thread_id == use_thread_id:
        raise _unsupported_harness_candidate("micro-harness support requires free/use on different threads")

    timing_applies_to = "use" if free_step["timestamp"] <= use_step["timestamp"] else "free"

    return HarnessTemplateContext(
        candidate_id=str(candidate.get("candidate_id", "")),
        family_id=SUPPORTED_FAMILY_ID,
        entry_function=SUPPORTED_ENTRY_FUNCTION,
        free_function=str(loc0.get("function", "")),
        free_file=str(loc0.get("file", "")),
        free_line=int(loc0.get("line", 0)),
        use_function=str(loc1.get("function", "")),
        use_file=str(loc1.get("file", "")),
        use_line=int(loc1.get("line", 0)),
        free_thread_id=free_thread_id,
        use_thread_id=use_thread_id,
        free_timestamp=free_step["timestamp"],
        use_timestamp=use_step["timestamp"],
        timing_applies_to=timing_applies_to,
    )


def render_kvm_timer_harness(context: HarnessTemplateContext) -> str:
    timing_free_expr = "timing_us" if context.timing_applies_to == "free" else "0"
    timing_use_expr = "timing_us" if context.timing_applies_to == "use" else "0"
    return dedent(
        f"""\
        // Auto-generated UAF verification harness
        // candidate_id: {context.candidate_id}
        // harness_family: {context.family_id}
        // predicted free: {context.free_function} ({context.free_file}:{context.free_line})
        // predicted use:  {context.use_function} ({context.use_file}:{context.use_line})
        // representative entry: {context.entry_function}
        // free thread id: {context.free_thread_id} timestamp={context.free_timestamp}
        // use thread id: {context.use_thread_id} timestamp={context.use_timestamp}
        // timing sweep applies to: {context.timing_applies_to}

        #define _GNU_SOURCE
        #include <errno.h>
        #include <fcntl.h>
        #include <linux/kvm.h>
        #include <pthread.h>
        #include <stdio.h>
        #include <stdlib.h>
        #include <string.h>
        #include <sys/ioctl.h>
        #include <sys/mman.h>
        #include <unistd.h>

        #ifndef KVM_ARM_TARGET_GENERIC_V8
        #define KVM_ARM_TARGET_GENERIC_V8 0
        #endif

        static int kvm_fd = -1;
        static int vm_fd = -1;
        static int vcpu_fd = -1;
        static void *run_area = MAP_FAILED;
        static size_t run_area_size = 0;
        static pthread_barrier_t race_barrier;
        static volatile int free_entered = 0;
        static volatile int use_entered = 0;

        struct thread_args {{
            int fd_snapshot;
            int delay_us;
        }};

        static int fail_setup(const char *stage) {{
            printf("HARNESS: setup_failed=1 stage=%s errno=%d\\n", stage, errno);
            fflush(stdout);
            return -1;
        }}

        static void cleanup_resources(void) {{
            if (run_area != MAP_FAILED && run_area_size > 0) {{
                munmap(run_area, run_area_size);
                run_area = MAP_FAILED;
                run_area_size = 0;
            }}
            if (vm_fd >= 0) {{
                close(vm_fd);
                vm_fd = -1;
            }}
            if (kvm_fd >= 0) {{
                close(kvm_fd);
                kvm_fd = -1;
            }}
        }}

        static int setup(void) {{
            kvm_fd = open("/dev/kvm", O_RDWR);
            if (kvm_fd < 0) {{
                return fail_setup("open_kvm");
            }}

            vm_fd = ioctl(kvm_fd, KVM_CREATE_VM, 0);
            if (vm_fd < 0) {{
                return fail_setup("create_vm");
            }}

            vcpu_fd = ioctl(vm_fd, KVM_CREATE_VCPU, 0);
            if (vcpu_fd < 0) {{
                return fail_setup("create_vcpu");
            }}

            errno = 0;
            run_area_size = (size_t)ioctl(kvm_fd, KVM_GET_VCPU_MMAP_SIZE, 0);
            if ((long)run_area_size <= 0) {{
                return fail_setup("get_vcpu_mmap_size");
            }}

            run_area = mmap(NULL, run_area_size, PROT_READ | PROT_WRITE, MAP_SHARED, vcpu_fd, 0);
            if (run_area == MAP_FAILED) {{
                return fail_setup("mmap_run_area");
            }}

            struct kvm_vcpu_init init;
            memset(&init, 0, sizeof(init));
            init.target = KVM_ARM_TARGET_GENERIC_V8;
            if (ioctl(vcpu_fd, KVM_ARM_VCPU_INIT, &init) < 0) {{
                return fail_setup("vcpu_init");
            }}

            printf("HARNESS: setup_ok=1\\n");
            fflush(stdout);
            return 0;
        }}

        static void *thread_free(void *arg) {{
            struct thread_args *args = (struct thread_args *)arg;
            int fd = args->fd_snapshot;
            int close_ret;
            int close_errno;
            int barrier_result = pthread_barrier_wait(&race_barrier);
            if (barrier_result != 0 && barrier_result != PTHREAD_BARRIER_SERIAL_THREAD) {{
                return NULL;
            }}
            if (args->delay_us > 0) {{
                usleep((useconds_t)args->delay_us);
            }}
            free_entered = 1;
            errno = 0;
            close_ret = close(fd);
            close_errno = errno;
            printf("HARNESS: event=free entered=1 thread={context.free_thread_id}\\n");
            printf("HARNESS: free_close_ret=%d errno=%d\\n", close_ret, close_errno);
            fflush(stdout);
            return NULL;
        }}

        static void *thread_use(void *arg) {{
            struct thread_args *args = (struct thread_args *)arg;
            int fd = args->fd_snapshot;
            int ioctl_ret;
            int ioctl_errno;
            int barrier_result = pthread_barrier_wait(&race_barrier);
            if (barrier_result != 0 && barrier_result != PTHREAD_BARRIER_SERIAL_THREAD) {{
                return NULL;
            }}
            if (args->delay_us > 0) {{
                usleep((useconds_t)args->delay_us);
            }}
            use_entered = 1;
            errno = 0;
            ioctl_ret = ioctl(fd, KVM_RUN, 0);
            ioctl_errno = errno;
            printf("HARNESS: event=use entered=1 thread={context.use_thread_id}\\n");
            printf("HARNESS: use_ioctl_ret=%d errno=%d\\n", ioctl_ret, ioctl_errno);
            fflush(stdout);
            return NULL;
        }}

        int main(int argc, char **argv) {{
            int timing_us = argc > 1 ? atoi(argv[1]) : 0;
            struct thread_args free_args;
            struct thread_args use_args;
            pthread_t free_thread;
            pthread_t use_thread;

            printf("HARNESS: candidate_id={context.candidate_id}\\n");
            printf("HARNESS: timing_us=%d\\n", timing_us);
            fflush(stdout);

            if (setup() < 0) {{
                cleanup_resources();
                return 2;
            }}

            free_args.fd_snapshot = vcpu_fd;
            free_args.delay_us = {timing_free_expr};
            use_args.fd_snapshot = vcpu_fd;
            use_args.delay_us = {timing_use_expr};

            if (pthread_barrier_init(&race_barrier, NULL, 2) != 0) {{
                errno = EBUSY;
                fail_setup("barrier_init");
                cleanup_resources();
                return 2;
            }}

            if (pthread_create(&free_thread, NULL, thread_free, &free_args) != 0) {{
                errno = EAGAIN;
                fail_setup("pthread_create_free");
                pthread_barrier_destroy(&race_barrier);
                cleanup_resources();
                return 2;
            }}

            if (pthread_create(&use_thread, NULL, thread_use, &use_args) != 0) {{
                errno = EAGAIN;
                fail_setup("pthread_create_use");
                pthread_join(free_thread, NULL);
                pthread_barrier_destroy(&race_barrier);
                cleanup_resources();
                return 2;
            }}

            pthread_join(free_thread, NULL);
            pthread_join(use_thread, NULL);
            pthread_barrier_destroy(&race_barrier);

            printf("HARNESS: candidate_reached=%d\\n", (free_entered || use_entered) ? 1 : 0);
            printf("HARNESS: timing_window_entered=%d\\n", (free_entered && use_entered) ? 1 : 0);
            printf("HARNESS: execution_completed=1\\n");
            printf("HARNESS: reached_no_crash=1\\n");
            fflush(stdout);

            cleanup_resources();
            return 0;
        }}
        """
    )

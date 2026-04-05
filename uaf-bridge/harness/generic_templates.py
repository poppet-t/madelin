from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Any


@dataclass(frozen=True)
class GenericHarnessContext:
    candidate_id: str
    subsystem: str
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


def _event_thread(plan: dict[str, Any], event_name: str) -> int:
    threads = plan.get("threads")
    if not isinstance(threads, list):
        return 0
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
    return 0


def _representative_entry(candidate: dict[str, Any]) -> tuple[str, str]:
    entries = candidate.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("candidate has no entries for generic harness generation")
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_func = entry.get("entry_func")
        entry_kind = entry.get("entry_kind")
        if isinstance(entry_func, str) and isinstance(entry_kind, str):
            return entry_func, entry_kind
    raise ValueError("candidate entries do not contain a representative entry function")


def build_generic_context(candidate: dict[str, Any], plan: dict[str, Any]) -> GenericHarnessContext:
    analysis_context = candidate.get("analysis_context")
    if not isinstance(analysis_context, dict):
        raise ValueError("candidate is missing analysis_context")
    subsystem = str(analysis_context.get("subsystem", "unknown"))
    entry_function, entry_kind = _representative_entry(candidate)
    loc0 = candidate.get("loc0") if isinstance(candidate.get("loc0"), dict) else {}
    loc1 = candidate.get("loc1") if isinstance(candidate.get("loc1"), dict) else {}
    family_id = {
        "io_uring": "io_uring_setup_enter_close_race",
        "net": "netlink_nft_dump_delete_race",
        "bpf": "bpf_link_detach_close_race",
        "fs": "fuse_control_teardown_race" if entry_kind == "fuse_control" else "mount_api_move_umount_race",
    }.get(subsystem, f"{subsystem}_generic_race")
    return GenericHarnessContext(
        candidate_id=str(candidate.get("candidate_id", "")),
        subsystem=subsystem,
        family_id=family_id,
        entry_function=entry_function,
        free_function=str(loc0.get("function", "")),
        free_file=str(loc0.get("file", "")),
        free_line=int(loc0.get("line", 0) or 0),
        use_function=str(loc1.get("function", "")),
        use_file=str(loc1.get("file", "")),
        use_line=int(loc1.get("line", 0) or 0),
        free_thread_id=_event_thread(plan, "free"),
        use_thread_id=_event_thread(plan, "use"),
    )


def _render_io_uring(context: GenericHarnessContext) -> str:
    return dedent(
        f"""\
        // Auto-generated hardware-light UAF verification harness
        // candidate_id: {context.candidate_id}
        // harness_family: {context.family_id}
        // predicted free: {context.free_function} ({context.free_file}:{context.free_line})
        // predicted use:  {context.use_function} ({context.use_file}:{context.use_line})
        // representative entry: {context.entry_function}

        #define _GNU_SOURCE
        #include <fcntl.h>
        #include <linux/io_uring.h>
        #include <pthread.h>
        #include <stdint.h>
        #include <stdio.h>
        #include <string.h>
        #include <sys/syscall.h>
        #include <unistd.h>

        static pthread_barrier_t barrier;
        static int ring_fd = -1;

        static void *thread_free(void *arg) {{
            pthread_barrier_wait(&barrier);
            close(ring_fd);
            printf("HARNESS: event=free thread={context.free_thread_id}\\n");
            return NULL;
        }}

        static void *thread_use(void *arg) {{
            pthread_barrier_wait(&barrier);
            syscall(__NR_io_uring_enter, ring_fd, 1, 1, 0, NULL, 0);
            printf("HARNESS: event=use thread={context.use_thread_id}\\n");
            return NULL;
        }}

        int main(void) {{
            struct io_uring_params params;
            int fds[1] = {{-1}};
            pthread_t t_free, t_use;

            memset(&params, 0, sizeof(params));
            ring_fd = syscall(__NR_io_uring_setup, 8, &params);
            syscall(__NR_io_uring_register, ring_fd, IORING_REGISTER_FILES, fds, 1);
            pthread_barrier_init(&barrier, NULL, 2);
            pthread_create(&t_free, NULL, thread_free, NULL);
            pthread_create(&t_use, NULL, thread_use, NULL);
            pthread_join(t_free, NULL);
            pthread_join(t_use, NULL);
            return 0;
        }}
        """
    )


def _render_net(context: GenericHarnessContext) -> str:
    return dedent(
        f"""\
        // Auto-generated hardware-light UAF verification harness
        // candidate_id: {context.candidate_id}
        // harness_family: {context.family_id}
        // representative entry: {context.entry_function}

        #define _GNU_SOURCE
        #include <linux/netlink.h>
        #include <pthread.h>
        #include <stdio.h>
        #include <string.h>
        #include <sys/socket.h>
        #include <unistd.h>

        static pthread_barrier_t barrier;
        static int nl_fd = -1;

        static void *thread_free(void *arg) {{
            pthread_barrier_wait(&barrier);
            close(nl_fd);
            printf("HARNESS: event=free thread={context.free_thread_id}\\n");
            return NULL;
        }}

        static void *thread_use(void *arg) {{
            struct msghdr msg;
            memset(&msg, 0, sizeof(msg));
            pthread_barrier_wait(&barrier);
            recvmsg(nl_fd, &msg, 0);
            printf("HARNESS: event=use thread={context.use_thread_id}\\n");
            return NULL;
        }}

        int main(void) {{
            pthread_t t_free, t_use;
            struct msghdr msg;
            memset(&msg, 0, sizeof(msg));
            nl_fd = socket(AF_NETLINK, SOCK_RAW, NETLINK_NETFILTER);
            sendmsg(nl_fd, &msg, 0);
            pthread_barrier_init(&barrier, NULL, 2);
            pthread_create(&t_free, NULL, thread_free, NULL);
            pthread_create(&t_use, NULL, thread_use, NULL);
            pthread_join(t_free, NULL);
            pthread_join(t_use, NULL);
            return 0;
        }}
        """
    )


def _render_bpf(context: GenericHarnessContext) -> str:
    return dedent(
        f"""\
        // Auto-generated hardware-light UAF verification harness
        // candidate_id: {context.candidate_id}
        // harness_family: {context.family_id}
        // representative entry: {context.entry_function}

        #define _GNU_SOURCE
        #include <linux/bpf.h>
        #include <pthread.h>
        #include <stdio.h>
        #include <string.h>
        #include <sys/syscall.h>
        #include <unistd.h>

        static pthread_barrier_t barrier;
        static int map_fd = -1;
        static int prog_fd = -1;
        static int link_fd = -1;

        static void *thread_free(void *arg) {{
            pthread_barrier_wait(&barrier);
            close(link_fd);
            close(prog_fd);
            close(map_fd);
            printf("HARNESS: event=free thread={context.free_thread_id}\\n");
            return NULL;
        }}

        static void *thread_use(void *arg) {{
            union bpf_attr attr;
            memset(&attr, 0, sizeof(attr));
            pthread_barrier_wait(&barrier);
            syscall(__NR_bpf, BPF_MAP_UPDATE_ELEM, &attr, sizeof(attr));
            printf("HARNESS: event=use thread={context.use_thread_id}\\n");
            return NULL;
        }}

        int main(void) {{
            union bpf_attr attr;
            pthread_t t_free, t_use;
            memset(&attr, 0, sizeof(attr));
            map_fd = syscall(__NR_bpf, BPF_MAP_CREATE, &attr, sizeof(attr));
            prog_fd = syscall(__NR_bpf, BPF_PROG_LOAD, &attr, sizeof(attr));
            link_fd = syscall(__NR_bpf, BPF_LINK_CREATE, &attr, sizeof(attr));
            pthread_barrier_init(&barrier, NULL, 2);
            pthread_create(&t_free, NULL, thread_free, NULL);
            pthread_create(&t_use, NULL, thread_use, NULL);
            pthread_join(t_free, NULL);
            pthread_join(t_use, NULL);
            return 0;
        }}
        """
    )


def _render_fs(context: GenericHarnessContext) -> str:
    return dedent(
        f"""\
        // Auto-generated hardware-light UAF verification harness
        // candidate_id: {context.candidate_id}
        // harness_family: {context.family_id}
        // representative entry: {context.entry_function}

        #define _GNU_SOURCE
        #include <pthread.h>
        #include <stdio.h>
        #include <sys/mount.h>
        #include <sys/syscall.h>
        #include <unistd.h>

        static pthread_barrier_t barrier;
        static int fs_fd = -1;
        static int mount_fd = -1;

        static void *thread_free(void *arg) {{
            pthread_barrier_wait(&barrier);
            close(mount_fd);
            close(fs_fd);
            printf("HARNESS: event=free thread={context.free_thread_id}\\n");
            return NULL;
        }}

        static void *thread_use(void *arg) {{
            pthread_barrier_wait(&barrier);
            syscall(__NR_move_mount, mount_fd, "", AT_FDCWD, "/tmp/madelin", 0);
            umount2("/tmp/madelin", 0);
            printf("HARNESS: event=use thread={context.use_thread_id}\\n");
            return NULL;
        }}

        int main(void) {{
            pthread_t t_free, t_use;
            fs_fd = syscall(__NR_fsopen, "tmpfs", 0);
            syscall(__NR_fsconfig, fs_fd, 1, "size", "4096", 0);
            mount_fd = syscall(__NR_fsmount, fs_fd, 0, 0);
            pthread_barrier_init(&barrier, NULL, 2);
            pthread_create(&t_free, NULL, thread_free, NULL);
            pthread_create(&t_use, NULL, thread_use, NULL);
            pthread_join(t_free, NULL);
            pthread_join(t_use, NULL);
            return 0;
        }}
        """
    )


def render_generic_harness(candidate: dict[str, Any], plan: dict[str, Any]) -> str:
    context = build_generic_context(candidate, plan)
    if context.subsystem == "io_uring":
        return _render_io_uring(context)
    if context.subsystem == "net":
        return _render_net(context)
    if context.subsystem == "bpf":
        return _render_bpf(context)
    if context.subsystem == "fs":
        return _render_fs(context)
    raise ValueError(f"unsupported generic harness subsystem: {context.subsystem}")

pub fn host_target_arch() -> &'static str {
    #[cfg(target_arch = "x86_64")]
    {
        return "amd64";
    }
    #[cfg(target_arch = "x86")]
    {
        return "386";
    }
    #[cfg(target_arch = "aarch64")]
    {
        return "arm64";
    }
    #[cfg(target_arch = "arm")]
    {
        return "arm";
    }
    #[cfg(target_arch = "mips64el")]
    {
        return "mips64le";
    }
    #[cfg(target_arch = "ppc64")]
    {
        return "ppc64le";
    }
    #[cfg(target_arch = "riscv64")]
    {
        return "riscv64";
    }
    #[cfg(target_arch = "s390x")]
    {
        return "s390x";
    }
    #[allow(unreachable_code)]
    "amd64"
}

pub const WALL_CLOCK: &[&str] = &[
    "datetime.date.today",
    "datetime.datetime.now",
    "datetime.datetime.today",
    "datetime.datetime.utcnow",
    "time.time",
    "time.time_ns",
];
pub const ENVIRONMENT: &[&str] = &["os.environ", "os.environb", "os.getenv", "os.getenvb"];
pub const NONDETERMINISTIC: &[&str] = &[
    "datetime.date.today",
    "datetime.datetime.now",
    "datetime.datetime.today",
    "datetime.datetime.utcnow",
    "os.urandom",
    "time.monotonic",
    "time.monotonic_ns",
    "time.perf_counter",
    "time.perf_counter_ns",
    "time.time",
    "time.time_ns",
    "uuid.uuid1",
    "uuid.uuid4",
    "uuid.uuid6",
    "uuid.uuid7",
];
pub const RANDOM_APIS: &[&str] = &[
    "Random",
    "SystemRandom",
    "choice",
    "choices",
    "expovariate",
    "gauss",
    "getrandbits",
    "normalvariate",
    "randbytes",
    "randint",
    "random",
    "randrange",
    "sample",
    "seed",
    "shuffle",
    "triangular",
    "uniform",
];
pub const SECRETS_APIS: &[&str] = &[
    "SystemRandom",
    "choice",
    "randbelow",
    "randbits",
    "token_bytes",
    "token_hex",
    "token_urlsafe",
];
pub const PATH_EFFECTS: &[&str] = &[
    "absolute",
    "chmod",
    "cwd",
    "exists",
    "expanduser",
    "glob",
    "group",
    "hardlink_to",
    "home",
    "is_dir",
    "is_file",
    "is_symlink",
    "iterdir",
    "lstat",
    "mkdir",
    "open",
    "owner",
    "read_bytes",
    "read_text",
    "readlink",
    "rename",
    "replace",
    "resolve",
    "rglob",
    "rmdir",
    "stat",
    "symlink_to",
    "touch",
    "unlink",
    "walk",
    "write_bytes",
    "write_text",
];
pub const LOG_METHODS: &[&str] = &[
    "addHandler",
    "basicConfig",
    "critical",
    "debug",
    "error",
    "exception",
    "fatal",
    "getLogger",
    "get_logger",
    "info",
    "log",
    "removeHandler",
    "setLevel",
    "warn",
    "warning",
];
pub const ASYNC_APIS: &[&str] = &[
    "TaskGroup",
    "create_task",
    "ensure_future",
    "gather",
    "get_event_loop",
    "get_running_loop",
    "run",
    "sleep",
    "to_thread",
    "wait",
    "wait_for",
];
pub const AMBIENT: &[&str] = &[
    "contextvars.copy_context",
    "decimal.getcontext",
    "decimal.setcontext",
    "locale.getlocale",
    "locale.setlocale",
    "os.chdir",
    "os.getcwd",
    "os.getcwdb",
    "os.putenv",
    "os.unsetenv",
];
pub const IO_PACKAGES: &[&str] = &[
    "aiohttp",
    "aiosqlite",
    "asyncpg",
    "boto3",
    "botocore",
    "httpx",
    "playwright",
    "psycopg",
    "psycopg2",
    "redis",
    "requests",
    "socket",
    "sqlite3",
    "subprocess",
];
pub fn nondeterministic(name: &str) -> bool {
    let (module, member) = name.rsplit_once('.').unwrap_or(("", name));
    NONDETERMINISTIC.contains(&name)
        || module == "random" && RANDOM_APIS.contains(&member)
        || module == "secrets" && SECRETS_APIS.contains(&member)
}
pub fn environment(name: &str) -> bool {
    ENVIRONMENT.contains(&name)
        || name.starts_with("os.environ.")
        || name.starts_with("os.environb.")
}
pub fn ambient(name: &str) -> bool {
    AMBIENT.contains(&name)
        || [
            "contextvars.ContextVar.get",
            "contextvars.ContextVar.set",
            "contextvars.ContextVar.reset",
        ]
        .contains(&name)
}
pub fn asynchronous(name: &str) -> bool {
    name.starts_with("asyncio.") && ASYNC_APIS.contains(&name.rsplit('.').next().unwrap_or(""))
        || [
            "threading.Thread",
            "multiprocessing.Process",
            "concurrent.futures.ThreadPoolExecutor",
            "concurrent.futures.ProcessPoolExecutor",
        ]
        .contains(&name)
}
pub fn io(name: &str) -> bool {
    let (module, member) = name.rsplit_once('.').unwrap_or(("", name));
    IO_PACKAGES.contains(&name.split('.').next().unwrap_or(""))
        || [
            "builtins.open",
            "builtins.print",
            "builtins.input",
            "io.open",
            "io.FileIO",
            "io.open_code",
        ]
        .contains(&name)
        || ["pathlib.Path", "pathlib.PosixPath", "pathlib.WindowsPath"].contains(&module)
            && PATH_EFFECTS.contains(&member)
        || [
            "logging",
            "logging.Logger",
            "logging.LoggerAdapter",
            "structlog",
            "structlog.BoundLogger",
        ]
        .contains(&module)
            && LOG_METHODS.contains(&member)
        || [
            "urllib.request.",
            "shutil.",
            "tempfile.",
            "sys.stdout.",
            "sys.stderr.",
            "sys.stdin.",
        ]
        .iter()
        .any(|p| name.starts_with(p))
        || module == "os"
            && [
                "open", "read", "write", "stat", "listdir", "scandir", "walk", "remove", "unlink",
                "mkdir", "makedirs", "rename", "replace", "system", "popen", "fork", "kill",
            ]
            .contains(&member)
        || module == "sys" && ["exit", "settrace", "setprofile"].contains(&member)
}

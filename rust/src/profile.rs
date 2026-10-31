//! Opt-in phase timings. Disabled builds compile the spans away.
#[cfg(feature = "profile")]
mod enabled {
    use std::{
        collections::BTreeMap,
        sync::{Mutex, OnceLock},
        time::Instant,
    };
    static TIMES: OnceLock<Mutex<BTreeMap<&'static str, (u64, u128)>>> = OnceLock::new();
    pub struct Span {
        name: &'static str,
        start: Instant,
    }
    impl Drop for Span {
        fn drop(&mut self) {
            let elapsed = self.start.elapsed().as_nanos();
            let mut times = TIMES.get_or_init(Default::default).lock().unwrap();
            let entry = times.entry(self.name).or_default();
            entry.0 += 1;
            entry.1 += elapsed;
        }
    }
    pub fn span(name: &'static str) -> Span {
        Span {
            name,
            start: Instant::now(),
        }
    }
    pub fn print() {
        let times = TIMES.get_or_init(Default::default).lock().unwrap();
        let result: BTreeMap<_, _> = times
            .iter()
            .map(|(name, (calls, ns))| {
                (
                    *name,
                    serde_json::json!({"calls":calls,"milliseconds":*ns as f64 / 1_000_000.0}),
                )
            })
            .collect();
        eprintln!("{}", serde_json::to_string(&result).unwrap());
    }
}
#[cfg(feature = "profile")]
pub use enabled::{print, span};
#[cfg(not(feature = "profile"))]
#[inline(always)]
pub fn span(_: &'static str) -> Span {
    Span
}
#[cfg(not(feature = "profile"))]
pub struct Span;
#[cfg(not(feature = "profile"))]
impl Drop for Span {
    fn drop(&mut self) {}
}
#[cfg(not(feature = "profile"))]
#[inline(always)]
pub fn print() {}

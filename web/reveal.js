// Scroll-reveal: content fades and rises into place as it enters the viewport.
// Progressive enhancement: nothing is hidden unless this module runs, and it does nothing
// when the user prefers reduced motion or IntersectionObserver is unavailable.

const TARGETS = [
  ".hero h1",
  ".hero .subtitle",
  ".hero .cta-row",
  ".section > h2",
  ".section > .section-note",
  ".tabs",
  ".search-form",
  ".carousel",
  ".chips",
  ".result-hero",
  ".summary",
  "#tags",
  ".next-step",
  ".results h3",
  ".pair",
  ".project",
  ".sources details",
].join(",");

// Explicit delays for the hero so it settles in sequence; grids stagger by sibling index.
const HERO_DELAYS = { H1: 0, P: 90, DIV: 180 };
const STAGGER_STEP = 70;
const STAGGER_MAX = 350;

let observer = null;

function delayFor(element) {
  if (element.closest(".hero")) return HERO_DELAYS[element.tagName] ?? 0;
  if (element.matches(".pair, .project")) {
    const index = Array.prototype.indexOf.call(element.parentElement.children, element);
    return Math.min(index * STAGGER_STEP, STAGGER_MAX);
  }
  return 0;
}

export function initReveal() {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced || !("IntersectionObserver" in window)) return;

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      }
    },
    { threshold: 0.12, rootMargin: "0px 0px -6% 0px" },
  );
  document.documentElement.classList.add("js-reveal");
  observeAll(document);
}

// Safe to call again after rendering new content; already-bound elements are skipped.
export function observeAll(root) {
  if (!observer) return;
  for (const element of root.querySelectorAll(TARGETS)) {
    if (element.dataset.revealBound) continue;
    element.dataset.revealBound = "1";
    element.style.setProperty("--reveal-delay", `${delayFor(element)}ms`);
    element.classList.add("reveal");
    observer.observe(element);
  }
}

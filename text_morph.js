// Vanilla-JS port of componentry.dev's Text Morph component
// (https://componentry.dev/docs/components/text-morph), adapted for Streamlit's
// st.components.v2 raw-JS mounting convention. The animation algorithm (constants,
// timing curves, gooey SVG filter) is ported 1:1 from the original TSX source; only the
// React-specific plumbing (hooks, refs) is replaced with plain closures and DOM APIs,
// since none of the actual visual effect depends on React.

const MORPH_BLUR = 12;
const MORPH_THRESHOLD = 18;
const DEFAULT_WORDS = ["IMAGINE", "REFINE", "RELEASE"];

let instanceCounter = 0;

function clamp(value, minimum = 0, maximum = 1) {
  return Math.min(maximum, Math.max(minimum, value));
}

function smoothstep(value) {
  const progress = clamp(value);
  return progress * progress * (3 - 2 * progress);
}

function setLayerStyles(element, opacity, blur, scale) {
  element.style.opacity = opacity.toFixed(4);
  element.style.filter = blur > 0.01 ? `blur(${blur.toFixed(2)}px)` : "none";
  element.style.transform = `translateX(-50%) scale(${scale.toFixed(4)})`;
}

function normalizeWords(words) {
  const filtered = (words || [])
    .map((word) => String(word))
    .filter((word) => word.trim().length > 0);
  return filtered.length > 0 ? filtered : DEFAULT_WORDS.slice();
}

function createTextMorph(root) {
  const filterId = `text-morph-threshold-${++instanceCounter}-${Date.now().toString(36)}`;

  root.innerHTML = `
    <svg aria-hidden="true" focusable="false" class="text-morph-svg">
      <defs>
        <filter id="${filterId}" x="-50%" y="-50%" width="200%" height="200%" color-interpolation-filters="sRGB">
          <feColorMatrix in="SourceGraphic" type="matrix"
            values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 ${MORPH_THRESHOLD} ${-MORPH_THRESHOLD * 0.46}"
            result="thresholded" />
          <feComposite in="SourceGraphic" in2="thresholded" operator="atop" />
        </filter>
      </defs>
    </svg>
    <span class="text-morph-stage">
      <span class="text-morph-layer text-morph-layer-current"></span>
      <span class="text-morph-layer text-morph-layer-next"></span>
    </span>
  `;
  root.setAttribute("aria-live", "off");

  const stage = root.querySelector(".text-morph-stage");
  const currentLayer = root.querySelector(".text-morph-layer-current");
  const nextLayer = root.querySelector(".text-morph-layer-next");

  const state = {
    values: DEFAULT_WORDS.slice(),
    lastRequestedWords: null,
    interval: 2600,
    morphDuration: 680,
    currentIndex: 0,
    holdTimer: undefined,
    frame: undefined,
    morphing: false,
    disposed: false,
    reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  };

  const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  const onReducedMotionChange = () => {
    state.reducedMotion = reducedMotionQuery.matches;
  };
  reducedMotionQuery.addEventListener("change", onReducedMotionChange);

  const safeIndex = () => state.currentIndex % state.values.length;
  const peekNextIndex = () => (safeIndex() + 1) % state.values.length;

  function renderWords() {
    currentLayer.textContent = state.values[safeIndex()];
    nextLayer.textContent = state.values[peekNextIndex()];
    root.setAttribute("aria-label", state.values[safeIndex()]);
  }

  function measureStage(immediate) {
    const width = currentLayer.offsetWidth;
    const height = currentLayer.offsetHeight;
    if (immediate || state.reducedMotion) {
      const previousTransition = stage.style.transition;
      stage.style.transition = "none";
      stage.style.width = `${width}px`;
      stage.style.height = `${height}px`;
      void stage.offsetWidth;
      stage.style.transition = previousTransition;
      return;
    }
    stage.style.width = `${width}px`;
    stage.style.height = `${height}px`;
  }

  function measureNextStage() {
    stage.style.width = `${nextLayer.offsetWidth}px`;
    stage.style.height = `${nextLayer.offsetHeight}px`;
  }

  function resetLayersForCurrentIndex() {
    renderWords();
    setLayerStyles(currentLayer, 1, 0, 1);
    setLayerStyles(nextLayer, 0, state.reducedMotion ? 0 : MORPH_BLUR, 0.992);
    currentLayer.style.willChange = "auto";
    nextLayer.style.willChange = "auto";
    stage.style.filter = "none";
    const duration = Math.max(160, state.morphDuration);
    stage.style.transition = state.reducedMotion
      ? "none"
      : `width ${duration}ms cubic-bezier(0.22, 1, 0.36, 1), height ${duration}ms cubic-bezier(0.22, 1, 0.36, 1)`;
    measureStage(true);
  }

  function scheduleNext() {
    window.clearTimeout(state.holdTimer);
    if (state.values.length < 2 || state.disposed) return;
    state.holdTimer = window.setTimeout(beginMorph, Math.max(400, state.interval));
  }

  function beginMorph() {
    if (state.morphing || state.values.length < 2 || state.disposed) return;

    state.morphing = true;
    currentLayer.style.willChange = "opacity, filter, transform";
    nextLayer.style.willChange = "opacity, filter, transform";
    stage.style.filter = state.reducedMotion ? "none" : `url(#${filterId})`;
    measureNextStage();

    const startedAt = performance.now();
    const resolvedDuration = state.reducedMotion ? 140 : Math.max(240, state.morphDuration);
    const nextIdx = peekNextIndex();

    function renderFrame(now) {
      const progress = clamp((now - startedAt) / resolvedDuration);
      const eased = smoothstep(progress);

      if (state.reducedMotion) {
        setLayerStyles(currentLayer, 1 - eased, 0, 1);
        setLayerStyles(nextLayer, eased, 0, 1);
      } else {
        // The incoming layer starts early and the outgoing layer lingers. Their
        // overlap gives the threshold filter enough shared alpha to feel fluid.
        const incoming = smoothstep(clamp(progress / 0.82));
        const outgoing = smoothstep(clamp((progress - 0.18) / 0.82));

        setLayerStyles(currentLayer, Math.pow(1 - outgoing, 0.55), MORPH_BLUR * outgoing, 1 - outgoing * 0.012);
        setLayerStyles(nextLayer, Math.pow(incoming, 0.55), MORPH_BLUR * (1 - incoming), 0.988 + incoming * 0.012);
      }

      if (progress < 1 && !state.disposed) {
        state.frame = window.requestAnimationFrame(renderFrame);
        return;
      }

      stage.style.filter = "none";
      currentLayer.style.willChange = "auto";
      nextLayer.style.willChange = "auto";
      state.morphing = false;
      state.currentIndex = nextIdx;
      if (!state.disposed) {
        resetLayersForCurrentIndex();
        scheduleNext();
      }
    }

    state.frame = window.requestAnimationFrame(renderFrame);
  }

  function setWords(words, interval, morphDuration) {
    const requestedKey = JSON.stringify(words || []);
    if (
      requestedKey === state.lastRequestedWords &&
      interval === state.interval &&
      morphDuration === state.morphDuration
    ) {
      // Nothing changed since last mount call (e.g. an unrelated Streamlit rerun) —
      // leave the running cycle alone instead of restarting it from word 0.
      return;
    }

    state.lastRequestedWords = requestedKey;
    state.values = normalizeWords(words);
    state.interval = interval;
    state.morphDuration = morphDuration;
    state.currentIndex = 0;

    window.cancelAnimationFrame(state.frame);
    state.morphing = false;
    resetLayersForCurrentIndex();
    scheduleNext();
  }

  const resizeObserver = new ResizeObserver(() => {
    if (!state.morphing) measureStage(true);
  });
  resizeObserver.observe(currentLayer);
  resizeObserver.observe(nextLayer);

  return {
    setWords,
    dispose() {
      state.disposed = true;
      window.clearTimeout(state.holdTimer);
      window.cancelAnimationFrame(state.frame);
      resizeObserver.disconnect();
      reducedMotionQuery.removeEventListener("change", onReducedMotionChange);
    },
  };
}

export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector(".text-morph-root");
  if (!root) {
    throw new Error("Unexpected: .text-morph-root element not found");
  }

  if (!root.__textMorphInstance) {
    root.__textMorphInstance = createTextMorph(root);
  }
  root.__textMorphInstance.setWords(data.words, data.interval, data.morphDuration);

  return () => {
    if (root.__textMorphInstance) {
      root.__textMorphInstance.dispose();
      delete root.__textMorphInstance;
    }
  };
}

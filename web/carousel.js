// Horizontal tile carousel for GitHub search results: scroll-snap strip with prev/next arrows.
// All GitHub-sourced strings are written with textContent, never innerHTML.

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function safeGithubUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "github.com" ? url.href : null;
  } catch {
    return null;
  }
}

export function createCarousel(root, { onToggle }) {
  const prev = el("button", "carousel-arrow", "‹");
  prev.type = "button";
  prev.setAttribute("aria-label", "Previous projects");
  const next = el("button", "carousel-arrow", "›");
  next.type = "button";
  next.setAttribute("aria-label", "Next projects");
  const viewport = el("div", "carousel-viewport");
  viewport.tabIndex = 0;
  viewport.setAttribute("aria-label", "Search results");
  root.replaceChildren(prev, viewport, next);

  const tiles = new Map();

  function step() {
    const first = viewport.querySelector(".tile");
    if (!first) return viewport.clientWidth;
    const gap = parseFloat(getComputedStyle(viewport).columnGap) || 0;
    return first.getBoundingClientRect().width + gap;
  }

  function updateArrows() {
    prev.disabled = viewport.scrollLeft <= 2;
    next.disabled = viewport.scrollLeft + viewport.clientWidth >= viewport.scrollWidth - 2;
  }

  prev.addEventListener("click", () => viewport.scrollBy({ left: -step(), behavior: "smooth" }));
  next.addEventListener("click", () => viewport.scrollBy({ left: step(), behavior: "smooth" }));
  viewport.addEventListener("scroll", updateArrows, { passive: true });
  window.addEventListener("resize", updateArrows);

  function paintSelected(tile, isSelected) {
    tile.classList.toggle("is-selected", isSelected);
    const button = tile.querySelector(".tile-add");
    button.textContent = isSelected ? "Added" : "Add";
    button.setAttribute("aria-pressed", String(isSelected));
  }

  function buildTile(item) {
    const tile = el("article", "tile");
    tile.appendChild(el("h3", "tile-name", item.full_name));
    const privateMark = item.private ? " · Private" : "";
    tile.appendChild(el("p", "tile-meta", `★ ${(Number(item.stars) || 0).toLocaleString()} · ${item.language || "Unknown"}${privateMark}`));
    tile.appendChild(el("p", "tile-desc", item.description || ""));

    const links = el("div", "tile-links");
    const href = safeGithubUrl(item.url);
    if (href) {
      const learn = el("a", "text-link", "Learn");
      learn.href = href;
      learn.target = "_blank";
      learn.rel = "noopener noreferrer";
      links.appendChild(learn);
    }
    const add = el("button", "text-link tile-add", "Add");
    add.type = "button";
    add.addEventListener("click", () => onToggle(item.full_name));
    links.appendChild(add);
    tile.appendChild(links);
    return tile;
  }

  return {
    setItems(items) {
      tiles.clear();
      viewport.replaceChildren();
      for (const item of items) {
        const tile = buildTile(item);
        tiles.set(item.full_name, tile);
        viewport.appendChild(tile);
      }
      viewport.scrollLeft = 0;
      requestAnimationFrame(updateArrows);
    },
    setSelected(selectedNames) {
      for (const [name, tile] of tiles) paintSelected(tile, selectedNames.has(name));
    },
  };
}

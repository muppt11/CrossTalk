// Horizontally-scrollable card strip for picking GitHub search results, replacing the old
// multiselect dropdown + dataframe combo. Click (or Enter/Space) toggles a card's selection;
// selection is reported back to Python via setStateValue, the same v2 bridge text_morph.js
// receives but never needed to call (this component is interactive, not decorative).

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value === undefined || value === null ? "" : String(value);
  return div.innerHTML;
}

function formatStars(stars) {
  return (Number(stars) || 0).toLocaleString();
}

function buildCard(item) {
  const card = document.createElement("div");
  card.className = "card-selector-card";
  card.dataset.id = item.full_name;
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  card.setAttribute("aria-pressed", "false");
  card.innerHTML = `
    <div class="card-selector-name">${escapeHtml(item.full_name)}</div>
    <div class="card-selector-meta">★ ${formatStars(item.stars)} &middot; ${escapeHtml(item.language || "Unknown")}</div>
    <div class="card-selector-desc">${escapeHtml(item.description || "")}</div>
  `;
  return card;
}

function createCardSelector(root, setStateValue) {
  root.innerHTML = `
    <div class="card-selector-row">
      <button type="button" class="card-selector-arrow card-selector-prev" aria-label="Scroll left">‹</button>
      <div class="card-selector-viewport"></div>
      <button type="button" class="card-selector-arrow card-selector-next" aria-label="Scroll right">›</button>
    </div>
  `;

  const viewport = root.querySelector(".card-selector-viewport");
  const prevButton = root.querySelector(".card-selector-prev");
  const nextButton = root.querySelector(".card-selector-next");

  const state = {
    itemsKey: null,
    selected: new Set(),
  };

  function scrollStep() {
    const firstCard = viewport.querySelector(".card-selector-card");
    if (!firstCard) return 240;
    const style = window.getComputedStyle(viewport);
    const gap = parseFloat(style.columnGap || style.gap || "0") || 0;
    return firstCard.getBoundingClientRect().width + gap;
  }

  prevButton.addEventListener("click", () => {
    viewport.scrollBy({ left: -scrollStep(), behavior: "smooth" });
  });
  nextButton.addEventListener("click", () => {
    viewport.scrollBy({ left: scrollStep(), behavior: "smooth" });
  });

  function toggleCard(card) {
    const id = card.dataset.id;
    if (state.selected.has(id)) {
      state.selected.delete(id);
      card.classList.remove("selected");
      card.setAttribute("aria-pressed", "false");
    } else {
      state.selected.add(id);
      card.classList.add("selected");
      card.setAttribute("aria-pressed", "true");
    }
    setStateValue("selected", Array.from(state.selected));
  }

  function setItems(items) {
    const safeItems = items || [];
    const requestedKey = JSON.stringify(safeItems.map((item) => item.full_name));
    if (requestedKey === state.itemsKey) {
      // Same result set as last render (e.g. an unrelated Streamlit rerun) — leave the
      // strip and current selection alone.
      return;
    }

    state.itemsKey = requestedKey;
    state.selected = new Set();
    viewport.innerHTML = "";

    safeItems.forEach((item) => {
      const card = buildCard(item);
      card.addEventListener("click", () => toggleCard(card));
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          toggleCard(card);
        }
      });
      viewport.appendChild(card);
    });

    setStateValue("selected", []);
  }

  return { setItems };
}

export default function (component) {
  const { data, parentElement, setStateValue } = component;
  const root = parentElement.querySelector(".card-selector-root");
  if (!root) {
    throw new Error("Unexpected: .card-selector-root element not found");
  }

  if (!root.__cardSelectorInstance) {
    root.__cardSelectorInstance = createCardSelector(root, setStateValue);
  }
  root.__cardSelectorInstance.setItems(data.items);

  return () => {
    delete root.__cardSelectorInstance;
  };
}

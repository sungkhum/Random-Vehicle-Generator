const data = window.VEHICLE_DATA;

const state = {
  selectedCategories: new Set(data.categories.map((category) => category.id)),
  currentVehicle: null,
};

const byId = Object.fromEntries(data.categories.map((category) => [category.id, category]));
const groupOrder = ["Air", "Land", "Road", "Rail", "Sea", "Space"];
const groupToneClass = {
  Air: "air",
  Land: "land",
  Road: "road",
  Rail: "rail",
  Sea: "sea",
  Space: "space",
};

const heroStats = document.querySelector("#hero-stats");
const selectionSummary = document.querySelector("#selection-summary");
const poolSummary = document.querySelector("#pool-summary");
const categoryGroups = document.querySelector("#category-groups");
const vehicleName = document.querySelector("#vehicle-name");
const vehicleDescription = document.querySelector("#vehicle-description");
const vehicleTags = document.querySelector("#vehicle-tags");
const vehicleSources = document.querySelector("#vehicle-sources");
const sourceList = document.querySelector("#source-list");
const resultCard = document.querySelector("#result-card");
const generateButton = document.querySelector("#generate-button");
const selectAllButton = document.querySelector("#select-all");
const clearAllButton = document.querySelector("#clear-all");

function groupedCategories() {
  return groupOrder
    .map((group) => ({
      group,
      categories: data.categories.filter((category) => category.group === group),
    }))
    .filter((entry) => entry.categories.length > 0);
}

function filteredVehicles() {
  return data.vehicles.filter((vehicle) =>
    vehicle.categories.some((categoryId) => state.selectedCategories.has(categoryId)),
  );
}

function randomVehicle() {
  const pool = filteredVehicles();
  if (!pool.length) {
    return null;
  }

  const index = Math.floor(Math.random() * pool.length);
  return pool[index];
}

function categoryChip(categoryId) {
  const category = byId[categoryId];
  const chip = document.createElement("span");
  chip.className = `chip ${groupToneClass[category.group].toLowerCase()}`;
  chip.textContent = category.label;
  return chip;
}

function renderHeroStats() {
  heroStats.innerHTML = "";
  const stats = [
    `${data.summary.vehicleCount.toLocaleString()} vehicles`,
    `${data.summary.categoryCount} filter categories`,
    "Open references from Wikidata + Wikipedia",
  ];

  stats.forEach((value) => {
    const pill = document.createElement("span");
    pill.className = "stat-pill";
    pill.textContent = value;
    heroStats.appendChild(pill);
  });
}

function renderCategoryFilters() {
  categoryGroups.innerHTML = "";

  groupedCategories().forEach(({ group, categories }) => {
    const wrapper = document.createElement("section");
    wrapper.className = "group-card";

    const heading = document.createElement("div");
    heading.className = "group-heading";
    heading.innerHTML = `<h3>${group}</h3><span>${categories.length} categories</span>`;

    const grid = document.createElement("div");
    grid.className = "checkbox-grid";

    categories.forEach((category) => {
      const tile = document.createElement("label");
      tile.className = "category-tile";

      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = state.selectedCategories.has(category.id);
      input.addEventListener("change", () => {
        if (input.checked) {
          state.selectedCategories.add(category.id);
        } else {
          state.selectedCategories.delete(category.id);
        }
        renderStatus();
      });

      const title = document.createElement("strong");
      title.textContent = category.label;

      const meta = document.createElement("span");
      meta.textContent = `${category.count.toLocaleString()} vehicles`;

      tile.append(input, title, meta);
      grid.appendChild(tile);
    });

    wrapper.append(heading, grid);
    categoryGroups.appendChild(wrapper);
  });
}

function renderVehicle(vehicle) {
  vehicleTags.innerHTML = "";
  vehicleSources.innerHTML = "";

  if (!vehicle) {
    resultCard.dataset.empty = "true";
    vehicleName.textContent = "No vehicles found";
    vehicleDescription.textContent =
      "Your current filter combination is empty. Turn some categories back on and try again.";
    return;
  }

  resultCard.dataset.empty = "false";
  vehicleName.textContent = vehicle.name;
  vehicleDescription.textContent =
    vehicle.description || "Pulled from the active filter pool with open-source vehicle references.";

  vehicle.categories.forEach((categoryId) => {
    vehicleTags.appendChild(categoryChip(categoryId));
  });

  const links = vehicle.sourceUrls.slice(0, 3);
  links.forEach((url, index) => {
    const anchor = document.createElement("a");
    anchor.className = "source-link";
    anchor.href = url;
    anchor.target = "_blank";
    anchor.rel = "noreferrer";
    anchor.textContent = `Source ${index + 1}`;
    vehicleSources.appendChild(anchor);
  });
}

function renderStatus() {
  const selectedCount = state.selectedCategories.size;
  const pool = filteredVehicles();

  selectionSummary.textContent =
    selectedCount === data.categories.length
      ? "All categories active"
      : `${selectedCount} categories active`;

  poolSummary.textContent = `${pool.length.toLocaleString()} vehicles in the current pool`;
  generateButton.disabled = pool.length === 0;

  if (state.currentVehicle && !pool.includes(state.currentVehicle)) {
    state.currentVehicle = null;
  }

  if (!state.currentVehicle) {
    renderVehicle(null);
  } else {
    renderVehicle(state.currentVehicle);
  }
}

function renderSources() {
  sourceList.innerHTML = "";

  const cards = [...data.sources, ...data.licenses];
  cards.forEach((source) => {
    const card = document.createElement("article");
    card.className = "source-card";

    const title = document.createElement("strong");
    title.textContent = source.label;

    const copy = document.createElement("p");
    copy.textContent =
      source.label.includes("CC0")
        ? "Structured data source used for model and family lookups."
        : source.label.includes("Wikipedia")
          ? "List pages used where titles were cleaner than raw entity classes."
          : "Direct source page used while building the local vehicle catalog.";

    const link = document.createElement("a");
    link.className = source.label.includes("CC0") || source.label.includes("Wikipedia")
      ? "license-link"
      : "source-link";
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = "Open source";

    card.append(title, copy, link);
    sourceList.appendChild(card);
  });
}

function generate() {
  state.currentVehicle = randomVehicle();
  renderVehicle(state.currentVehicle);
  renderStatus();
}

generateButton.addEventListener("click", generate);

selectAllButton.addEventListener("click", () => {
  data.categories.forEach((category) => state.selectedCategories.add(category.id));
  renderCategoryFilters();
  renderStatus();
});

clearAllButton.addEventListener("click", () => {
  state.selectedCategories.clear();
  renderCategoryFilters();
  renderStatus();
});

renderHeroStats();
renderCategoryFilters();
renderSources();
generate();

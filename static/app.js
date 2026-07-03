const state = {
  data: null,
  city: "NYC",
  tab: "Museums",
  query: "",
  useImageProxy: true
};

const citySelect = document.querySelector("#citySelect");
const tabs = document.querySelector("#tabs");
const searchInput = document.querySelector("#searchInput");
const currentGrid = document.querySelector("#currentGrid");
const upcomingGrid = document.querySelector("#upcomingGrid");
const currentCount = document.querySelector("#currentCount");
const upcomingCount = document.querySelector("#upcomingCount");
const updatedAt = document.querySelector("#updatedAt");
const cardTemplate = document.querySelector("#cardTemplate");
const cityLabel = document.querySelector("#cityLabel");
const searchLabel = document.querySelector("#searchLabel");
const currentHeading = document.querySelector("#currentHeading");
const upcomingHeading = document.querySelector("#upcomingHeading");

const labels = {
  en: {
    city: "City",
    search: "Search",
    searchPlaceholder: "Artist, venue, exhibition",
    current: "On View Now",
    upcoming: "Upcoming",
    source: "Source",
    empty: "No exhibitions found.",
    updated: "Updated",
    notRefreshed: "Not refreshed yet",
    exhibition: "exhibition",
    exhibitions: "exhibitions",
    through: "Through",
    opens: "Opens",
    to: "through"
  },
  ru: {
    city: "Город",
    search: "Поиск",
    searchPlaceholder: "Художник, музей, выставка",
    current: "Сейчас",
    upcoming: "Скоро",
    source: "Источник",
    empty: "Выставки не найдены.",
    updated: "Обновлено",
    notRefreshed: "Пока не обновлялось",
    exhibition: "выставка",
    exhibitions: "выставок",
    through: "До",
    opens: "С",
    to: "по"
  }
};

const russianMonths = [
  "",
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря"
];

init();

async function init() {
  state.data = await loadExhibitionData();
  state.city = state.data.cities?.[0] || "NYC";
  state.tab = state.data.tabs?.[0] || "Museums";
  renderControls();
  render();

  citySelect.addEventListener("change", () => {
    state.city = citySelect.value;
    ensureActiveTab();
    renderControls();
    render();
  });
  searchInput.addEventListener("input", () => {
    state.query = searchInput.value.trim().toLowerCase();
    render();
  });
}

async function loadExhibitionData() {
  try {
    const response = await fetch("/api/exhibitions");
    if (response.ok) {
      state.useImageProxy = true;
      return await response.json();
    }
  } catch (_error) {
    // Static hosting has no Python API; fall through to the generated JSON file.
  }

  state.useImageProxy = false;
  const staticResponse = await fetch("data/exhibitions.json");
  if (!staticResponse.ok) {
    throw new Error("Could not load exhibition data.");
  }
  return await staticResponse.json();
}

function renderControls() {
  applyLocale();
  citySelect.innerHTML = "";
  for (const city of state.data.cities || ["NYC"]) {
    const option = document.createElement("option");
    option.value = city;
    option.textContent = city;
    citySelect.append(option);
  }
  citySelect.value = state.city;

  tabs.innerHTML = "";
  for (const tab of visibleTabs()) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = tab;
    button.className = tab === state.tab ? "active" : "";
    button.addEventListener("click", () => {
      state.tab = tab;
      renderControls();
      render();
    });
    tabs.append(button);
  }

  const t = currentLabels();
  updatedAt.textContent = state.data.generated_at
    ? `${t.updated} ${new Intl.DateTimeFormat(localeCode(), { dateStyle: "medium", timeStyle: "short" }).format(new Date(state.data.generated_at))}`
    : t.notRefreshed;
}

function render() {
  ensureActiveTab();
  const filtered = (state.data.exhibitions || []).filter((item) => {
    if (item.city !== state.city || item.tab !== state.tab) return false;
    if (!state.query) return true;
    return [item.title, item.venue, item.date_text]
      .join(" ")
      .toLowerCase()
      .includes(state.query);
  });

  const current = filtered.filter((item) => item.status === "current");
  const upcoming = filtered.filter((item) => item.status === "upcoming");
  renderGrid(currentGrid, sortExhibitions(current), { groupByVenue: shouldGroupCurrentGrid() });
  renderGrid(upcomingGrid, sortExhibitions(upcoming));
  currentCount.textContent = countLabel(current.length);
  upcomingCount.textContent = countLabel(upcoming.length);
}

function shouldGroupCurrentGrid() {
  return state.tab !== "Galleries";
}

function visibleTabs() {
  const tabsInCity = new Set(
    (state.data.exhibitions || [])
      .filter((item) => item.city === state.city)
      .map((item) => item.tab)
  );
  const configured = state.data.tabs || [];
  const visible = configured.filter((tab) => tabsInCity.has(tab));
  return visible.length ? visible : configured;
}

function ensureActiveTab() {
  const tabsForCity = visibleTabs();
  if (!tabsForCity.includes(state.tab)) {
    state.tab = tabsForCity[0] || state.tab;
  }
}

function sortExhibitions(items) {
  return [...items].sort((a, b) => {
    return (
      numberValue(a.venue_order) - numberValue(b.venue_order) ||
      (a.start_date || "9999-99-99").localeCompare(b.start_date || "9999-99-99") ||
      a.title.localeCompare(b.title)
    );
  });
}

function numberValue(value) {
  return Number.isFinite(Number(value)) ? Number(value) : 999;
}

function renderGrid(grid, items, options = {}) {
  grid.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = currentLabels().empty;
    grid.append(empty);
    return;
  }

  let currentVenue = "";
  for (const item of items) {
    const startsNewVenue = Boolean(options.groupByVenue && currentVenue && item.venue !== currentVenue);
    if (startsNewVenue) {
      grid.append(createVenueSeparator());
    }
    currentVenue = item.venue;
    grid.append(createCard(item, { startsNewVenue }));
  }
}

function createVenueSeparator() {
  const separator = document.createElement("div");
  separator.className = "venue-separator";
  separator.setAttribute("aria-hidden", "true");
  return separator;
}

function createCard(item, options = {}) {
  const node = cardTemplate.content.firstElementChild.cloneNode(true);
  if (options.startsNewVenue) {
    node.classList.add("venue-start");
  }

  const imageLink = node.querySelector(".image-link");
  const image = node.querySelector("img");
  const fallback = node.querySelector(".image-fallback");
  const title = node.querySelector("h3");
  const source = node.querySelector(".source-link");

  imageLink.href = item.source_url;
  source.href = item.source_url;
  source.textContent = currentLabels().source;
  title.textContent = item.title;
  node.querySelector(".venue").textContent = item.venue;
  node.querySelector(".dates").textContent = displayDateText(item);
  const location = node.querySelector(".location");
  if (item.location && item.location !== item.city && item.location !== item.venue) {
    location.textContent = item.location;
  } else {
    location.remove();
  }

  if (item.image_url) {
    fallback.textContent = item.venue;
    fallback.hidden = true;
    image.referrerPolicy = "no-referrer";
    image.loading = "lazy";
    image.decoding = "async";
    image.src = imageProxyUrl(item.image_url);
    image.alt = item.title;
    image.addEventListener("error", () => {
      image.remove();
      fallback.hidden = false;
    }, { once: true });
  } else {
    image.remove();
    fallback.textContent = item.venue;
  }

  return node;
}

function imageProxyUrl(url) {
  if (!url) return "";
  if (!state.useImageProxy) return url;
  return `/api/image?url=${encodeURIComponent(url)}`;
}

function countLabel(count) {
  const t = currentLabels();
  if (localeCode() === "ru-RU") {
    return `${count} ${t.exhibitions}`;
  }
  return `${count} ${count === 1 ? t.exhibition : t.exhibitions}`;
}

function applyLocale() {
  const t = currentLabels();
  document.documentElement.lang = localeCode() === "ru-RU" ? "ru" : "en";
  cityLabel.textContent = t.city;
  searchLabel.textContent = t.search;
  searchInput.placeholder = t.searchPlaceholder;
  currentHeading.textContent = t.current;
  upcomingHeading.textContent = t.upcoming;
}

function currentLabels() {
  return labels[state.city === "Moscow" ? "ru" : "en"];
}

function localeCode() {
  return state.city === "Moscow" ? "ru-RU" : undefined;
}

function displayDateText(item) {
  if (state.city !== "Moscow") {
    return item.date_text;
  }

  const end = parseIsoDate(item.end_date);
  const start = parseIsoDate(item.start_date);
  const t = currentLabels();
  if (item.status === "upcoming" && start && end) {
    return `${t.opens} ${formatRussianDate(start)} ${t.to} ${formatRussianDate(end)}`;
  }
  if (end) {
    return `${t.through} ${formatRussianDate(end)}`;
  }
  if (start && item.status === "upcoming") {
    return `${t.opens} ${formatRussianDate(start)}`;
  }
  return item.date_text;
}

function parseIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) {
    return null;
  }
  const [year, month, day] = value.split("-").map(Number);
  return { year, month, day };
}

function formatRussianDate(date) {
  return `${date.day} ${russianMonths[date.month]} ${date.year}`;
}

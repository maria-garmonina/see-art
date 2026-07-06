const state = {
  data: null,
  eventsData: null,
  city: "NYC",
  tab: "Museums",
  query: "",
  view: "exhibitions",
  eventFilter: "All",
  eventWeekStart: startOfWeek(new Date()),
  useImageProxy: true
};

const citySelect = document.querySelector("#citySelect");
const modeTabs = document.querySelector("#modeTabs");
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
const exhibitionsView = document.querySelector("#exhibitionsView");
const eventsView = document.querySelector("#eventsView");
const eventsList = document.querySelector("#eventsList");
const eventFilters = document.querySelector("#eventFilters");
const weekLabel = document.querySelector("#weekLabel");
const prevWeek = document.querySelector("#prevWeek");
const todayWeek = document.querySelector("#todayWeek");
const nextWeek = document.querySelector("#nextWeek");

const labels = {
  en: {
    city: "City",
    search: "Search",
    exhibitionSearchPlaceholder: "Artist, venue, exhibition",
    eventSearchPlaceholder: "Event, venue, category",
    current: "On View Now",
    upcoming: "Upcoming",
    source: "Details",
    details: "Details",
    googleCalendar: "Google Calendar",
    appleCalendar: "Apple Calendar",
    empty: "No exhibitions found.",
    emptyEvents: "No events found for this week.",
    updated: "Updated",
    notRefreshed: "Not refreshed yet",
    exhibition: "exhibition",
    exhibitions: "exhibitions",
    event: "event",
    events: "events",
    through: "Through",
    opens: "Opens",
    to: "through",
    exhibitionsView: "Exhibitions",
    eventsView: "Events",
    all: "All"
  },
  ru: {
    city: "Город",
    search: "Поиск",
    exhibitionSearchPlaceholder: "Художник, музей, выставка",
    eventSearchPlaceholder: "Событие, музей, категория",
    current: "Сейчас",
    upcoming: "Скоро",
    source: "Подробнее",
    details: "Подробнее",
    googleCalendar: "Google Calendar",
    appleCalendar: "Apple Calendar",
    empty: "Выставки не найдены.",
    emptyEvents: "События на этой неделе не найдены.",
    updated: "Обновлено",
    notRefreshed: "Пока не обновлялось",
    exhibition: "выставка",
    exhibitionsFew: "выставки",
    exhibitions: "выставок",
    event: "событие",
    events: "событий",
    through: "До",
    opens: "С",
    to: "по",
    exhibitionsView: "Выставки",
    eventsView: "События",
    all: "Все"
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
  const [exhibitionData, eventData] = await Promise.all([loadExhibitionData(), loadEventData()]);
  state.data = exhibitionData;
  state.eventsData = eventData;
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
  prevWeek.addEventListener("click", () => {
    state.eventWeekStart = addDays(state.eventWeekStart, -7);
    renderEventsView();
  });
  todayWeek.addEventListener("click", () => {
    state.eventWeekStart = startOfWeek(new Date());
    renderEventsView();
  });
  nextWeek.addEventListener("click", () => {
    state.eventWeekStart = addDays(state.eventWeekStart, 7);
    renderEventsView();
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

async function loadEventData() {
  try {
    const response = await fetch("/api/events");
    if (response.ok) {
      return await response.json();
    }
  } catch (_error) {
    // Static hosting has no Python API; fall through to the generated JSON file.
  }

  try {
    const staticResponse = await fetch("data/events.json");
    if (staticResponse.ok) {
      return await staticResponse.json();
    }
  } catch (_error) {
    // Older deploys may not have event data yet.
  }

  return {
    generated_at: null,
    cities: state.data?.cities || ["NYC"],
    timezone: "America/New_York",
    filters: ["Tours", "Talks", "Performances", "Family", "Free"],
    events: [],
    errors: []
  };
}

function renderControls() {
  applyLocale();
  renderCitySelect();
  renderModeTabs();
  renderVenueTabs();
  renderEventFilters();
  renderUpdatedAt();
}

function renderCitySelect() {
  citySelect.innerHTML = "";
  for (const city of state.data.cities || ["NYC"]) {
    const option = document.createElement("option");
    option.value = city;
    option.textContent = city;
    citySelect.append(option);
  }
  citySelect.value = state.city;
}

function renderModeTabs() {
  const t = currentLabels();
  modeTabs.innerHTML = "";
  for (const view of ["exhibitions", "events"]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = view === "exhibitions" ? t.exhibitionsView : t.eventsView;
    button.className = state.view === view ? "active" : "";
    button.addEventListener("click", () => {
      state.view = view;
      state.query = "";
      searchInput.value = "";
      renderControls();
      render();
    });
    modeTabs.append(button);
  }
}

function renderVenueTabs() {
  tabs.hidden = state.view !== "exhibitions";
  tabs.innerHTML = "";
  if (tabs.hidden) return;
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
}

function renderEventFilters() {
  eventFilters.innerHTML = "";
  const filters = ["All", ...(state.eventsData?.filters || [])];
  for (const filter of filters) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = filter === "All" ? currentLabels().all : filter;
    button.className = state.eventFilter === filter ? "active" : "";
    button.addEventListener("click", () => {
      state.eventFilter = filter;
      renderEventFilters();
      renderEventsView();
    });
    eventFilters.append(button);
  }
}

function renderUpdatedAt() {
  const t = currentLabels();
  const payload = state.view === "events" ? state.eventsData : state.data;
  updatedAt.textContent = payload?.generated_at
    ? `${t.updated} ${new Intl.DateTimeFormat(localeCode(), { dateStyle: "medium", timeStyle: "short" }).format(new Date(payload.generated_at))}`
    : t.notRefreshed;
}

function render() {
  if (state.view === "events") {
    exhibitionsView.hidden = true;
    eventsView.hidden = false;
    renderEventsView();
    return;
  }
  exhibitionsView.hidden = false;
  eventsView.hidden = true;
  renderExhibitionsView();
}

function renderExhibitionsView() {
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
  currentCount.textContent = countLabel(current.length, "exhibition");
  upcomingCount.textContent = countLabel(upcoming.length, "exhibition");
}

function renderEventsView() {
  renderUpdatedAt();
  const weekStart = state.eventWeekStart;
  const weekEnd = addDays(weekStart, 6);
  weekLabel.textContent = `${formatWeekDate(weekStart)} - ${formatWeekDate(weekEnd)}`;

  const events = eventsForCurrentWeek();
  eventsList.innerHTML = "";
  if (!events.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = currentLabels().emptyEvents;
    eventsList.append(empty);
    return;
  }

  for (let offset = 0; offset < 7; offset += 1) {
    const day = addDays(weekStart, offset);
    const dayEvents = events.filter((event) => isSameDay(parseLocalDateTime(event.start_at), day));
    const section = document.createElement("section");
    section.className = "event-day";
    const heading = document.createElement("div");
    heading.className = "event-day-heading";
    heading.innerHTML = `<h2>${formatDayLabel(day)}</h2><p>${countLabel(dayEvents.length, "event")}</p>`;
    section.append(heading);

    if (!dayEvents.length) {
      const quiet = document.createElement("p");
      quiet.className = "quiet-day";
      quiet.textContent = currentLabels().emptyEvents;
      section.append(quiet);
    } else {
      for (const event of dayEvents) {
        section.append(createEventItem(event));
      }
    }
    eventsList.append(section);
  }
}

function eventsForCurrentWeek() {
  const weekStart = state.eventWeekStart;
  const weekEnd = addDays(weekStart, 7);
  return (state.eventsData?.events || [])
    .filter((event) => event.city === state.city)
    .filter((event) => {
      const start = parseLocalDateTime(event.start_at);
      return start && start >= weekStart && start < weekEnd;
    })
    .filter((event) => eventMatchesFilter(event))
    .filter((event) => {
      if (!state.query) return true;
      return [event.title, event.venue, event.category, event.location, event.price_text]
        .join(" ")
        .toLowerCase()
        .includes(state.query);
    })
    .sort((a, b) => a.start_at.localeCompare(b.start_at) || a.venue.localeCompare(b.venue));
}

function eventMatchesFilter(event) {
  if (state.eventFilter === "All") return true;
  if (state.eventFilter === "Free") {
    return event.price === 0 || /free/i.test(event.price_text || "");
  }
  return event.category === state.eventFilter;
}

function createEventItem(event) {
  const article = document.createElement("article");
  article.className = "event-item";
  const start = parseLocalDateTime(event.start_at);
  const end = parseLocalDateTime(event.end_at);
  const time = document.createElement("time");
  time.className = "event-time";
  time.dateTime = event.start_at;
  time.textContent = formatEventTime(start, end);

  const body = document.createElement("div");
  body.className = "event-body";
  const meta = document.createElement("p");
  meta.className = "event-meta";
  meta.textContent = [event.venue, event.category].filter(Boolean).join(" / ");
  const title = document.createElement("h3");
  title.textContent = event.title;
  const details = document.createElement("p");
  details.className = "event-details";
  details.textContent = [event.location, event.price_text, event.availability_text].filter(Boolean).join(" · ");

  const actions = document.createElement("div");
  actions.className = "event-actions";
  const source = document.createElement("a");
  source.href = event.source_url;
  source.target = "_blank";
  source.rel = "noreferrer";
  source.textContent = currentLabels().details;
  actions.append(source, createGoogleCalendarLink(event), createIcsLink(event));

  body.append(meta, title, details, actions);
  article.append(time, body);
  return article;
}

function createGoogleCalendarLink(event) {
  const start = parseLocalDateTime(event.start_at);
  const end = parseLocalDateTime(event.end_at);
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: event.title,
    dates: `${formatGoogleDate(start)}/${formatGoogleDate(end)}`,
    ctz: event.timezone || state.eventsData?.timezone || "America/New_York",
    details: `${event.venue}\n${event.price_text || ""}\n${event.source_url}`,
    location: event.location || event.venue
  });
  const link = document.createElement("a");
  link.href = `https://calendar.google.com/calendar/render?${params.toString()}`;
  link.target = "_blank";
  link.rel = "noreferrer";
  link.textContent = currentLabels().googleCalendar;
  return link;
}

function createIcsLink(event) {
  const timezone = event.timezone || state.eventsData?.timezone || "America/New_York";
  const start = parseLocalDateTime(event.start_at);
  const end = parseLocalDateTime(event.end_at);
  const body = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//SeeArt//Events//EN",
    "BEGIN:VEVENT",
    `UID:${event.id}@seeart`,
    `DTSTAMP:${formatUtcDate(new Date())}`,
    `DTSTART;TZID=${timezone}:${formatIcsLocalDate(start)}`,
    `DTEND;TZID=${timezone}:${formatIcsLocalDate(end)}`,
    `SUMMARY:${escapeIcs(event.title)}`,
    `LOCATION:${escapeIcs(event.location || event.venue)}`,
    `DESCRIPTION:${escapeIcs([event.venue, event.price_text, event.source_url].filter(Boolean).join("\\n"))}`,
    `URL:${event.source_url}`,
    "END:VEVENT",
    "END:VCALENDAR"
  ].join("\r\n");
  const link = document.createElement("a");
  link.href = `data:text/calendar;charset=utf-8,${encodeURIComponent(body)}`;
  link.download = `${slugify(event.title)}.ics`;
  link.textContent = currentLabels().appleCalendar;
  return link;
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

function countLabel(count, kind = "exhibition") {
  const t = currentLabels();
  if (kind === "event") {
    return `${count} ${count === 1 ? t.event : t.events}`;
  }
  if (localeCode() === "ru-RU") {
    return `${count} ${russianPlural(count, t.exhibition, t.exhibitionsFew, t.exhibitions)}`;
  }
  return `${count} ${count === 1 ? t.exhibition : t.exhibitions}`;
}

function russianPlural(count, one, few, many) {
  const mod10 = Math.abs(count) % 10;
  const mod100 = Math.abs(count) % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

function applyLocale() {
  const t = currentLabels();
  document.documentElement.lang = localeCode() === "ru-RU" ? "ru" : "en";
  cityLabel.textContent = t.city;
  searchLabel.textContent = t.search;
  searchInput.placeholder = state.view === "events" ? t.eventSearchPlaceholder : t.exhibitionSearchPlaceholder;
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

function parseLocalDateTime(value) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value || "")) return null;
  const [datePart, timePart] = value.split("T");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute] = timePart.split(":").map(Number);
  return new Date(year, month - 1, day, hour, minute);
}

function startOfWeek(value) {
  const date = new Date(value.getFullYear(), value.getMonth(), value.getDate());
  const offset = (date.getDay() + 6) % 7;
  date.setDate(date.getDate() - offset);
  return date;
}

function addDays(value, days) {
  const date = new Date(value.getFullYear(), value.getMonth(), value.getDate());
  date.setDate(date.getDate() + days);
  return date;
}

function isSameDay(a, b) {
  return Boolean(a && b && a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate());
}

function formatWeekDate(date) {
  return new Intl.DateTimeFormat(localeCode(), { month: "short", day: "numeric" }).format(date);
}

function formatDayLabel(date) {
  return new Intl.DateTimeFormat(localeCode(), { weekday: "long", month: "short", day: "numeric" }).format(date);
}

function formatEventTime(start, end) {
  const formatter = new Intl.DateTimeFormat(localeCode(), { hour: "numeric", minute: "2-digit" });
  if (!start) return "";
  if (!end) return formatter.format(start);
  return `${formatter.format(start)} - ${formatter.format(end)}`;
}

function pad(value) {
  return String(value).padStart(2, "0");
}

function formatGoogleDate(date) {
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}T${pad(date.getHours())}${pad(date.getMinutes())}00`;
}

function formatIcsLocalDate(date) {
  return formatGoogleDate(date);
}

function formatUtcDate(date) {
  return `${date.getUTCFullYear()}${pad(date.getUTCMonth() + 1)}${pad(date.getUTCDate())}T${pad(date.getUTCHours())}${pad(date.getUTCMinutes())}${pad(date.getUTCSeconds())}Z`;
}

function escapeIcs(value) {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function slugify(value) {
  return String(value || "event")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60) || "event";
}

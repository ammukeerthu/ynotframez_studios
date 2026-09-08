const spaceList = document.querySelector("#marketing-space-list");

const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

function safe(value) {
  const element = document.createElement("span");
  element.textContent = value ?? "";
  return element.innerHTML;
}

function safeAttr(value) {
  return safe(value).replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function studioCard(space, index) {
  const firstFiveAmenities = Array.isArray(space.amenities) ? space.amenities.slice(0, 5) : [];
  const amenities = firstFiveAmenities.map((item) => `<span>${safe(item)}</span>`).join("");
  return `
    <article class="studio-story ${index % 2 ? "offset" : ""}">
      <a class="studio-image" href="/studios/${encodeURIComponent(space.slug)}">
        <img src="${safeAttr(space.cover_image)}" alt="${safeAttr(space.name)}" loading="lazy" decoding="async">
      </a>
      <div class="studio-meta">
        <div><p class="overline">SPACE 0${index + 1}</p><h3>${safe(space.name)}</h3><p>${safe(space.short_description)}</p></div>
        <div class="studio-rate"><small>FROM</small><strong>${money.format(space.hourly_rate)}</strong><span>/ hour</span></div>
      </div>
      <div class="amenities">${amenities}</div>
      <div class="studio-facts"><span>${safe(space.dimensions)}</span><span>Up to ${safe(space.capacity)} people</span></div>
      <div class="studio-actions"><a class="studio-link" href="/studios/${encodeURIComponent(space.slug)}">Explore the studio <span>→</span></a><a class="quick-book" href="/book?space=${encodeURIComponent(space.id)}">Book now</a></div>
    </article>`;
}

function renderStudioCards(spaces) {
  spaceList.innerHTML = spaces.map(studioCard).join("");
}

const cachedSpaces = window.YNFStudioCache?.read();
if (cachedSpaces) renderStudioCards(cachedSpaces);

fetch("/api/spaces", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error("Unable to load studios");
    return response.json();
  })
  .then((spaces) => {
    window.YNFStudioCache?.write(spaces);
    renderStudioCards(spaces);
  })
  .catch(() => {
    if (!cachedSpaces) {
      spaceList.innerHTML = '<p class="load-error">Studio information is temporarily unavailable. Please try again shortly.</p>';
    }
  });

document.querySelector("#year").textContent = new Date().getFullYear();

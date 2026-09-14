const spaceList = document.querySelector("#marketing-space-list");
let amenityCarouselCleanup = [];

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
  const amenities = Array.isArray(space.amenities)
    ? space.amenities.map((item) => `<span>${safe(item)}</span>`).join("")
    : "";
  return `
    <article class="studio-story ${index % 2 ? "offset" : ""}">
      <a class="studio-image" href="/studios/${encodeURIComponent(space.slug)}">
        <img src="${safeAttr(space.cover_image)}" alt="${safeAttr(space.name)}" loading="lazy" decoding="async">
      </a>
      <div class="studio-meta">
        <div><p class="overline">SPACE 0${index + 1}</p><h3>${safe(space.name)}</h3><p>${safe(space.short_description)}</p></div>
        <div class="studio-rate"><small>FROM</small><strong>${money.format(space.hourly_rate)}</strong><span>/ hour</span></div>
      </div>
      <div class="amenities-carousel" data-amenities-carousel role="region" aria-label="${safeAttr(space.name)} amenities">
        <div class="amenities-viewport" tabindex="0"><div class="amenities">${amenities}</div></div>
        <button class="amenity-navigation next" type="button" aria-label="Show more ${safeAttr(space.name)} amenities">→</button>
      </div>
      <div class="studio-facts"><span>${safe(space.dimensions)}</span><span>Up to ${safe(space.capacity)} people</span></div>
      <div class="studio-actions"><a class="studio-link" href="/studios/${encodeURIComponent(space.slug)}">Explore the studio <span>→</span></a><a class="quick-book" href="/book?space=${encodeURIComponent(space.id)}">Book now</a></div>
    </article>`;
}

function initializeAmenityCarousels() {
  amenityCarouselCleanup.forEach((cleanup) => cleanup());
  amenityCarouselCleanup = [];
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const scrollBehavior = reduceMotion ? "auto" : "smooth";

  document.querySelectorAll("[data-amenities-carousel]").forEach((carousel) => {
    const viewport = carousel.querySelector(".amenities-viewport");
    const next = carousel.querySelector(".amenity-navigation.next");

    const hasOverflow = () => viewport.scrollWidth > viewport.clientWidth + 2;
    const updateOverflowState = () => carousel.classList.toggle("static", !hasOverflow());
    const move = (direction) => {
      if (!hasOverflow()) return;
      const maximum = viewport.scrollWidth - viewport.clientWidth;
      const atStart = viewport.scrollLeft <= 2;
      const atEnd = viewport.scrollLeft >= maximum - 2;
      if (direction < 0 && atStart) viewport.scrollTo({ left: maximum, behavior: scrollBehavior });
      else if (direction > 0 && atEnd) viewport.scrollTo({ left: 0, behavior: scrollBehavior });
      else viewport.scrollBy({ left: direction * Math.max(viewport.clientWidth * 0.72, 150), behavior: scrollBehavior });
    };
    const showNext = () => move(1);

    next.addEventListener("click", showNext);

    const resizeObserver = typeof ResizeObserver === "function"
      ? new ResizeObserver(updateOverflowState)
      : null;
    resizeObserver?.observe(viewport);
    updateOverflowState();

    amenityCarouselCleanup.push(() => {
      resizeObserver?.disconnect();
      next.removeEventListener("click", showNext);
    });
  });
}

function renderStudioCards(spaces) {
  spaceList.innerHTML = spaces.map(studioCard).join("");
  window.requestAnimationFrame(initializeAmenityCarousels);
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

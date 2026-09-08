const slug = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).pop() || "");
const detailRoot = document.querySelector("#studio-detail");
const errorRoot = document.querySelector("#studio-error");
const galleryRoot = document.querySelector("#detail-gallery");
const galleryDialog = document.querySelector("#studio-gallery-dialog");
const galleryPreview = document.querySelector("#gallery-preview");
const galleryCaption = document.querySelector("#gallery-caption");
const galleryPrevious = document.querySelector("#gallery-previous");
const galleryNext = document.querySelector("#gallery-next");
const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
let galleryImages = [];
let gallerySpaceName = "Studio";
let galleryIndex = 0;

function setText(selector, value) {
  document.querySelector(selector).textContent = value;
}

function updateGalleryPreview(index) {
  if (!galleryImages.length || !galleryPreview || !galleryCaption) return;
  galleryIndex = (index + galleryImages.length) % galleryImages.length;
  galleryPreview.src = galleryImages[galleryIndex];
  galleryPreview.alt = `${gallerySpaceName} studio view ${galleryIndex + 1}`;
  galleryCaption.textContent = `${gallerySpaceName} · ${galleryIndex + 1} of ${galleryImages.length}`;
}

function openGallery(index) {
  updateGalleryPreview(index);
  if (galleryDialog?.showModal) galleryDialog.showModal();
}

function renderGallery(space) {
  if (!galleryRoot) return;
  galleryImages = Array.isArray(space.gallery_images) ? space.gallery_images.filter(Boolean) : [];
  gallerySpaceName = space.name;
  galleryRoot.replaceChildren();
  galleryRoot.classList.toggle("single", galleryImages.length === 1);
  const gallerySection = galleryRoot.closest(".studio-gallery");
  if (gallerySection) gallerySection.hidden = galleryImages.length === 0;
  galleryImages.forEach((source, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "studio-gallery-item";
    button.setAttribute("aria-label", `Open ${space.name} studio image ${index + 1}`);
    const image = document.createElement("img");
    image.src = source;
    image.alt = `${space.name} studio view ${index + 1}`;
    image.loading = "lazy";
    image.decoding = "async";
    button.append(image);
    button.addEventListener("click", () => openGallery(index));
    galleryRoot.append(button);
  });
  const showNavigation = galleryImages.length > 1;
  if (galleryPrevious) galleryPrevious.hidden = !showNavigation;
  if (galleryNext) galleryNext.hidden = !showNavigation;
}

document.querySelector("#gallery-close")?.addEventListener("click", () => galleryDialog?.close());
galleryPrevious?.addEventListener("click", () => updateGalleryPreview(galleryIndex - 1));
galleryNext?.addEventListener("click", () => updateGalleryPreview(galleryIndex + 1));
galleryDialog?.addEventListener("click", (event) => {
  if (event.target === galleryDialog) galleryDialog.close();
});
galleryDialog?.addEventListener("keydown", (event) => {
  if (event.key === "ArrowLeft") updateGalleryPreview(galleryIndex - 1);
  if (event.key === "ArrowRight") updateGalleryPreview(galleryIndex + 1);
});

function renderStudio(space) {
  document.title = `${space.name} | YNotFramez Studios`;
  const image = document.querySelector("#detail-image");
  image.src = space.hero_image || space.cover_image;
  image.alt = `${space.name} photography studio`;
  setText("#detail-name", space.name);
  setText("#detail-short", space.short_description);
  setText("#detail-statement", space.id === "standard_small" ? "Small in footprint.\nBig on possibility." : "Built for ideas\nthat need more room.");
  document.querySelector("#detail-statement").style.whiteSpace = "pre-line";
  setText("#detail-description", space.brochure);
  setText("#detail-capacity", `Up to ${space.capacity} people`);
  setText("#detail-dimensions", space.dimensions);
  setText("#detail-rate", `${money.format(space.hourly_rate)} / hour`);
  setText("#detail-minimum", `${space.min_duration_hours} hours`);
  setText("#detail-cta-title", `Make ${space.name} yours.`);
  setText("#detail-cta-price", `From ${money.format(space.hourly_rate)} per hour`);
  renderGallery(space);

  const inclusions = [...(space.equipment || []), ...(space.amenities || [])].filter(
    (item, index, values) => values.findIndex(
      (candidate) => candidate.trim().toLocaleLowerCase() === item.trim().toLocaleLowerCase(),
    ) === index,
  );
  document.querySelector("#detail-amenities").innerHTML = inclusions
    .map((amenity, index) => `<li><span>${String(index + 1).padStart(2, "0")}</span><b></b></li>`)
    .join("");
  document.querySelectorAll("#detail-amenities li").forEach((item, index) => {
    item.querySelector("b").textContent = inclusions[index];
  });

  const rules = space.rules
    .split(/\r?\n+|\.\s+(?=[A-Z])/)
    .map((rule) => rule.trim())
    .filter(Boolean);
  document.querySelector("#detail-rules").innerHTML = rules.map(() => "<li></li>").join("");
  document.querySelectorAll("#detail-rules li").forEach((item, index) => {
    item.textContent = rules[index].replace(/^Rules:\s*/i, "").replace(/\.$/, "");
  });

  const bookingUrl = `/book?space=${encodeURIComponent(space.id)}`;
  document.querySelector("#detail-book-link").href = bookingUrl;
  document.querySelector("#nav-book-space").href = bookingUrl;
}

const cachedSpace = window.YNFStudioCache?.findBySlug(slug);
if (cachedSpace) renderStudio(cachedSpace);

fetch(`/api/spaces/${encodeURIComponent(slug)}`, { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error("Studio not found");
    return response.json();
  })
  .then((space) => {
    window.YNFStudioCache?.upsert(space);
    renderStudio(space);
  })
  .catch(() => {
    if (!cachedSpace) {
      detailRoot.hidden = true;
      errorRoot.hidden = false;
    }
  });

document.querySelector("#year").textContent = new Date().getFullYear();

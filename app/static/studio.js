const slug = decodeURIComponent(window.location.pathname.split("/").filter(Boolean).pop() || "");
const detailRoot = document.querySelector("#studio-detail");
const errorRoot = document.querySelector("#studio-error");
const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

function setText(selector, value) {
  document.querySelector(selector).textContent = value;
}

fetch(`/api/spaces/${encodeURIComponent(slug)}`)
  .then((response) => {
    if (!response.ok) throw new Error("Studio not found");
    return response.json();
  })
  .then((space) => {
    document.title = `${space.name} | YNotFramez Studios`;
    const image = document.querySelector("#detail-image");
    image.src = space.cover_image;
    image.alt = `${space.name} photography studio`;
    setText("#detail-name", space.name);
    setText("#detail-short", space.short_description);
    setText("#detail-statement", space.id === "standard_small" ? "Small in footprint.\nBig on possibility." : "Built for ideas\nthat need more room.");
    document.querySelector("#detail-statement").style.whiteSpace = "pre-line";
    setText("#detail-description", space.brochure);
    setText("#detail-capacity", `Up to ${space.capacity} people`);
    setText("#detail-dimensions", space.dimensions);
    setText("#detail-rate", `${money.format(space.hourly_rate)} / hour`);
    setText("#detail-cta-title", `Make ${space.name} yours.`);
    setText("#detail-cta-price", `From ${money.format(space.hourly_rate)} per hour`);

    const inclusions = [...new Set([...(space.equipment || []), ...space.amenities])];
    document.querySelector("#detail-amenities").innerHTML = inclusions
      .map((amenity, index) => `<li><span>${String(index + 1).padStart(2, "0")}</span><b></b><p></p></li>`)
      .join("");
    document.querySelectorAll("#detail-amenities li").forEach((item, index) => {
      item.querySelector("b").textContent = inclusions[index];
      item.querySelector("p").textContent = "Included in your hourly studio reservation.";
    });

    const rules = space.rules.split(/,\s+|\.\s+/).map((rule) => rule.trim()).filter(Boolean);
    document.querySelector("#detail-rules").innerHTML = rules.map(() => "<li></li>").join("");
    document.querySelectorAll("#detail-rules li").forEach((item, index) => {
      item.textContent = rules[index].replace(/^Rules:\s*/i, "").replace(/\.$/, "");
    });

    const bookingUrl = `/book?space=${encodeURIComponent(space.id)}`;
    document.querySelector("#detail-book-link").href = bookingUrl;
    document.querySelector("#nav-book-space").href = bookingUrl;
  })
  .catch(() => {
    detailRoot.hidden = true;
    errorRoot.hidden = false;
  });

document.querySelector("#year").textContent = new Date().getFullYear();

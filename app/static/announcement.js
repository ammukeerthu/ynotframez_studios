(() => {
  const bar = document.querySelector("#public-announcement-bar");
  if (!bar) return;

  const labels = { news: "News", alert: "Alert", offer: "Offer", event: "Event" };
  fetch("/api/announcement", { cache: "no-store", headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) throw new Error("Announcement unavailable");
      return response.json();
    })
    .then((announcement) => {
      const category = labels[announcement.category] ? announcement.category : "news";
      const message = String(announcement.message || "").trim();
      if (!announcement.enabled || !message) return;
      bar.dataset.category = category;
      bar.querySelector(".announcement-bar__label").textContent = labels[category];
      bar.querySelector(".announcement-bar__message").textContent = message;
      bar.hidden = false;
    })
    .catch(() => {
      bar.hidden = true;
    });
})();

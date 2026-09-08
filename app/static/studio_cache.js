(function setupStudioCache() {
  const storageKey = "ynf.public-spaces.v1";
  const maximumAgeMs = 24 * 60 * 60 * 1000;

  function read() {
    try {
      const cached = JSON.parse(window.localStorage.getItem(storageKey) || "null");
      if (
        !cached
        || !Array.isArray(cached.spaces)
        || !Number.isFinite(cached.savedAt)
        || Date.now() - cached.savedAt > maximumAgeMs
      ) {
        return null;
      }
      return cached.spaces;
    } catch (_) {
      return null;
    }
  }

  function write(spaces) {
    if (!Array.isArray(spaces)) return;
    try {
      window.localStorage.setItem(storageKey, JSON.stringify({ savedAt: Date.now(), spaces }));
    } catch (_) {
      // Storage can be unavailable in private browsing; live API loading still works.
    }
  }

  function clear() {
    try {
      window.localStorage.removeItem(storageKey);
    } catch (_) {
      // Nothing else is required when browser storage is unavailable.
    }
  }

  function findBySlug(slug) {
    return read()?.find((space) => space.slug === slug) || null;
  }

  function upsert(space) {
    const spaces = read();
    if (!spaces || !space?.id) return;
    const index = spaces.findIndex((item) => item.id === space.id);
    if (index === -1) spaces.push(space);
    else spaces[index] = space;
    write(spaces);
  }

  window.YNFStudioCache = { clear, findBySlug, read, upsert, write };
})();

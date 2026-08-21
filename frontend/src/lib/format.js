/** Small presentation helpers, kept out of the components. */

/** "2 hours ago" — the form §11 asks for on a verified memory. */
export function relativeTime(iso) {
  if (!iso) return "never verified";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "never verified";
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 45) return "just now";
  const units = [
    ["minute", 60],
    ["hour", 3600],
    ["day", 86400],
    ["week", 604800],
    ["month", 2592000],
    ["year", 31536000],
  ];
  let label = "second";
  let size = 1;
  for (const [name, length] of units) {
    if (seconds < length) break;
    label = name;
    size = length;
  }
  const count = Math.floor(seconds / size);
  return `${count} ${label}${count === 1 ? "" : "s"} ago`;
}

/** Clock time for the event timeline. */
export function clockTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

/** `/Users/me/Documents/nexus` → `~/Documents/nexus`, for display only. */
export function shortenPath(path) {
  if (!path) return "";
  return path.replace(/^\/Users\/[^/]+/, "~");
}

/** The last segment of a path, which is what people call the project. */
export function basename(path) {
  if (!path) return "";
  const parts = path.replace(/\/+$/, "").split("/");
  return parts[parts.length - 1] || path;
}

/** A memory value rendered compactly: `port 8123`, `path ~/x`. */
export function summariseValue(value) {
  if (!value || typeof value !== "object") return String(value ?? "");
  return Object.entries(value)
    .map(([key, item]) => {
      const text = typeof item === "string" ? shortenPath(item) : String(item);
      return key === "path" ? text : `${key} ${text}`;
    })
    .join(" · ");
}

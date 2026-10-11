/** Remembers the reviewer name (actor_label) between visits. Storage can be unavailable, so never throw. */
const KEY = "recytrack.actor_label";

export function loadReviewer(): string {
  try {
    return window.localStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveReviewer(name: string): void {
  try {
    window.localStorage.setItem(KEY, name.trim());
  } catch {
    // Private mode or blocked storage: the name is simply not remembered.
  }
}

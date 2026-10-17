export const THEME_KEY = "focusos-theme";

/** Runs in <head> before paint so a saved choice never flashes the other theme. Kept out of the
 * client component module so the server layout receives the string itself. */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

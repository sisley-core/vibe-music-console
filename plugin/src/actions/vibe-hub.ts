/**
 * Shared hub: allows any vibe dial to trigger a refresh of ALL vibe dials.
 * Avoids circular dependencies between plugin.ts and dial action files.
 */

let _refreshAllVibeDials: ((vibe: any) => void) | null = null;

/** Called by plugin.ts at startup to register the global refresh function */
export function registerVibeRefresh(fn: (vibe: any) => void): void {
	_refreshAllVibeDials = fn;
}

/** Called by any dial's press handler to refresh all 3 vibe dials at once */
export function refreshAllVibeDials(vibe: any): void {
	_refreshAllVibeDials?.(vibe);
}

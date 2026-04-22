import streamDeck from "@elgato/streamdeck";
import { callApi } from "./api";
import { VolumeDial } from "./actions/volume-dial";
import { EnergyDial } from "./actions/energy-dial";
import { MoodDial } from "./actions/mood-dial";
import { DiscoveryDial } from "./actions/discovery-dial";
import { VibeButton } from "./actions/vibe-button";
import { registerVibeRefresh } from "./actions/vibe-hub";

// Create action instances with UUIDs (replaces @action decorator)
const volumeDial = new VolumeDial();
(volumeDial as any).manifestId = "com.vibe.console.volume";

const energyDial = new EnergyDial();
(energyDial as any).manifestId = "com.vibe.console.energy";

const moodDial = new MoodDial();
(moodDial as any).manifestId = "com.vibe.console.mood";

const discoveryDial = new DiscoveryDial();
(discoveryDial as any).manifestId = "com.vibe.console.discovery";

const vibeButton = new VibeButton();
(vibeButton as any).manifestId = "com.vibe.console.button";

// Register all actions
streamDeck.actions.registerAction(volumeDial);
streamDeck.actions.registerAction(energyDial);
streamDeck.actions.registerAction(moodDial);
streamDeck.actions.registerAction(discoveryDial);
streamDeck.actions.registerAction(vibeButton);

// Register shared refresh: any dial press can update all 3 vibe dials at once
registerVibeRefresh((vibe: any) => {
	energyDial.refreshAll(vibe);
	moodDial.refreshAll(vibe);
	discoveryDial.refreshAll(vibe);
});

// === Idle screensaver (replaces native sleep to preserve current profile) ===
const IDLE_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes
let lastActivity = Date.now();
let isDimmed = false;

// Export so polling and actions can check
export function isScreensaverActive(): boolean { return isDimmed; }

async function blankAll(): Promise<void> {
	let count = 0;
	for (const dev of streamDeck.devices) {
		for (const action of dev.actions) {
			try {
				// Keys: switch to state 1 (black icon) and clear title
				if (typeof (action as any).setState === "function") {
					await (action as any).setState(1);
					await (action as any).setTitle?.("");
				}
				// Dials: hide all layout elements
				if (typeof (action as any).setFeedback === "function") {
					await (action as any).setFeedback({
						value: { value: "", enabled: false },
						indicator: { value: 0, enabled: false }
					});
				}
				count++;
			} catch { /* skip */ }
		}
	}
	streamDeck.logger.info(`screensaver: ON (blanked ${count} actions)`);
}

async function restoreAll(): Promise<void> {
	for (const dev of streamDeck.devices) {
		for (const action of dev.actions) {
			try {
				if (typeof (action as any).setState === "function") {
					await (action as any).setState(0);
				}
				// Restore dial elements
				if (typeof (action as any).setFeedback === "function") {
					await (action as any).setFeedback({
						value: { enabled: true },
						indicator: { enabled: true }
					});
				}
			} catch { /* skip */ }
		}
	}
	streamDeck.logger.info("screensaver: OFF");
}

async function refreshOnce(): Promise<void> {
	try {
		const [glm, vibe] = await Promise.all([
			callApi("/glm/status").catch(() => null),
			callApi("/vibe/state").catch(() => null)
		]);
		volumeDial.refreshAll(glm, vibe);
		energyDial.refreshAll(vibe);
		moodDial.refreshAll(vibe);
		discoveryDial.refreshAll(vibe);
	} catch { /* skip */ }
}

function wakeUp(): void {
	lastActivity = Date.now();
	if (isDimmed) {
		isDimmed = false;
		restoreAll().then(() => refreshOnce());
	}
}

// Track user interactions to reset idle timer
streamDeck.actions.onDialRotate(() => wakeUp());
streamDeck.actions.onDialDown(() => wakeUp());
streamDeck.actions.onDialUp(() => wakeUp());
streamDeck.actions.onTouchTap(() => wakeUp());
streamDeck.actions.onKeyDown(() => wakeUp());
streamDeck.actions.onKeyUp(() => wakeUp());

// Check idle every 30 seconds
setInterval(() => {
	if (!isDimmed && Date.now() - lastActivity > IDLE_TIMEOUT_MS) {
		isDimmed = true;
		blankAll();
	}
}, 30_000);

// Global polling: fetch state once per second, update all 4 dials
setInterval(async () => {
	if (isDimmed) return;
	await refreshOnce();
}, 1000);

// Connect to Stream Deck (must be last)
streamDeck.connect();

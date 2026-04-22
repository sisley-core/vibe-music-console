import streamDeck from "@elgato/streamdeck";
/** Tracks last user interaction for auto-dimming */
export let lastActivity = Date.now();
export function markActive() {
	lastActivity = Date.now();
	streamDeck.logger.info("markActive");
}

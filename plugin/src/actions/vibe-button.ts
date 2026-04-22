import streamDeck, {
	SingletonAction,
	type KeyDownEvent,
	type KeyUpEvent,
	type WillAppearEvent
} from "@elgato/streamdeck";
import { callApi } from "../api";

type ButtonSettings = {
	url?: string;
	label?: string;
	switchProfile?: string;
};

export class VibeButton extends SingletonAction<ButtonSettings> {

	override async onWillAppear(ev: WillAppearEvent<ButtonSettings>): Promise<void> {
		const label = ev.payload.settings?.label;
		if (label) {
			await ev.action.setTitle(label);
		}
	}

	override async onKeyDown(ev: KeyDownEvent<ButtonSettings>): Promise<void> {
		const s = ev.payload.settings;
		streamDeck.logger.info(`VibeButton keyDown: url=${s?.url} label=${s?.label} sp=${s?.switchProfile}`);
		const url = s?.url;
		if (url) {
			try {
				await callApi(url);
				streamDeck.logger.info(`VibeButton OK: ${url}`);
			} catch (err) {
				streamDeck.logger.error(`VibeButton: ${err}`);
			}
		}
		const profile = ev.payload.settings?.switchProfile;
		if (profile) {
			await streamDeck.profiles.switchToProfile(ev.action.device.id, profile);
		}
	}

	override async onKeyUp(ev: KeyUpEvent<ButtonSettings>): Promise<void> {
		// SD auto-toggles multi-state actions; state 1 is only for screensaver
		await ev.action.setState(0);
	}
}

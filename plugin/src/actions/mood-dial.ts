import {
	SingletonAction,
	type WillAppearEvent,
	type DialRotateEvent,
	type DialUpEvent,
	type TouchTapEvent
} from "@elgato/streamdeck";
import { callApi } from "../api";
import { type AxisConfig, refreshAxisOne, handleAxisRotate, handleAxisPress } from "./vibe-dial-shared";

const CFG: AxisConfig = {
	axis: "mood",
	emoji: "🌗",
	label: "Mood",
	leftLabel: "暗",
	rightLabel: "亮",
	barColor: "#FFD600"
};

export class MoodDial extends SingletonAction {

	override async onWillAppear(ev: WillAppearEvent): Promise<void> {
		if (ev.action.isDial()) {
			const vibe = await callApi("/vibe/state").catch(() => null);
			refreshAxisOne(ev.action, vibe, CFG);
		}
	}

	override async onDialRotate(ev: DialRotateEvent): Promise<void> {
		await handleAxisRotate(ev.payload.ticks, CFG);
		const vibe = await callApi("/vibe/state").catch(() => null);
		this.refreshAll(vibe);
	}

	override async onDialUp(ev: DialUpEvent): Promise<void> {
		await handleAxisPress();
	}

	override async onTouchTap(ev: TouchTapEvent): Promise<void> {
		await handleAxisPress();
	}

	refreshAll(vibe: any): void {
		for (const a of this.actions) {
			if (a.isDial()) refreshAxisOne(a, vibe, CFG);
		}
	}
}

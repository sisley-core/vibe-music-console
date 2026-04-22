import streamDeck, {
	SingletonAction,
	type WillAppearEvent,
	type DialRotateEvent,
	type DialUpEvent,
	type TouchTapEvent
} from "@elgato/streamdeck";
import { callApi } from "../api";

export class VolumeDial extends SingletonAction {

	override async onWillAppear(ev: WillAppearEvent): Promise<void> {
		if (ev.action.isDial()) {
			const [glm, vibe] = await Promise.all([
				callApi("/glm/status").catch(() => null),
				callApi("/vibe/state").catch(() => null)
			]);
			this.refreshOne(ev.action, glm, vibe);
		}
	}

	override async onDialRotate(ev: DialRotateEvent): Promise<void> {
		const ticks = ev.payload.ticks;
		const endpoint = ticks > 0 ? "/glm/vol_up" : "/glm/vol_dn";
		// Fire vol changes sequentially for accuracy
		for (let i = 0; i < Math.abs(ticks); i++) {
			await callApi(endpoint).catch(() => null);
		}
		const [glm, vibe] = await Promise.all([
			callApi("/glm/status").catch(() => null),
			callApi("/vibe/state").catch(() => null)
		]);
		this.refreshAll(glm, vibe);
	}

	override async onDialUp(ev: DialUpEvent): Promise<void> {
		await callApi("/glm/mute").catch(() => null);
		const [glm, vibe] = await Promise.all([
			callApi("/glm/status").catch(() => null),
			callApi("/vibe/state").catch(() => null)
		]);
		this.refreshAll(glm, vibe);
	}

	override async onTouchTap(ev: TouchTapEvent): Promise<void> {
		await callApi("/glm/vol_0db").catch(() => null);
		const [glm, vibe] = await Promise.all([
			callApi("/glm/status").catch(() => null),
			callApi("/vibe/state").catch(() => null)
		]);
		this.refreshAll(glm, vibe);
	}

	/** Update all visible volume dial instances */
	refreshAll(glm: any, vibe: any): void {
		for (const a of this.actions) {
			if (a.isDial()) this.refreshOne(a, glm, vibe);
		}
	}

	private refreshOne(a: any, glm: any, vibe: any): void {
		const vol = glm?.volume;
		const group = glm?.group === "Movie" ? "AV" : (glm?.group || "HiFi");
		const muted = glm?.muted;
		const dbStr = typeof vol === "string" ? vol.replace(" dB", "") : String(vol ?? "?");
		const parsed = parseInt(dbStr);
		const dbNum = isNaN(parsed) ? -20 : parsed;

		const track = vibe?.current_track;
		const songText = track ? `♪ ${(track.song || "").substring(0, 22)}` : "";

		// Map dB range (-40..0) to 0..100 for bar
		const barVal = Math.max(0, Math.min(100, ((dbNum + 40) / 40) * 100));

		a.setFeedback({
			indicator: barVal,
			value: muted ? "🔇 MUTE" : `🔊 ${group} ${dbStr}dB`
		});
	}
}

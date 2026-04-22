import { callApi } from "../api";
import { refreshAllVibeDials } from "./vibe-hub";

/** Per-axis config */
export interface AxisConfig {
	axis: string;
	emoji: string;
	label: string;
	leftLabel: string;
	rightLabel: string;
	barColor: string;
}

/** Fetch fresh state and update one dial action's touch strip */
export function refreshAxisOne(a: any, vibe: any, cfg: AxisConfig): void {
	// If backend is generating, show waiting animation
	if (vibe?.status === "generating") {
		a.setFeedback({
			indicator: { value: 50, bar_fill_c: "#888888" },
			value: `${cfg.emoji} 生成中...`
		});
		return;
	}
	const val = vibe?.[cfg.axis] ?? 50;
	const word = val <= 50 ? cfg.leftLabel : cfg.rightLabel;
	a.setFeedback({
		indicator: { value: val, bar_fill_c: cfg.barColor },
		value: `${cfg.emoji} ${word} ${val}`
	});
}

/** Handle rotation: adjust axis by ticks*5 */
export async function handleAxisRotate(ticks: number, cfg: AxisConfig): Promise<void> {
	const delta = ticks * 5;
	await callApi(`/vibe/dial?axis=${cfg.axis}&delta=${delta}`).catch(() => null);
}

/** Handle press: stop playback, trigger AI generate, refresh ALL vibe dials */
export async function handleAxisPress(): Promise<any> {
	await callApi("/vibe/generate").catch(() => null);
	const vibe = await callApi("/vibe/state").catch(() => null);
	refreshAllVibeDials(vibe);
	return vibe;
}

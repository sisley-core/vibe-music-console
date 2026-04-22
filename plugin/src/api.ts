const BASE_URL = "http://localhost:8555";

export async function callApi(path: string): Promise<any> {
	const resp = await fetch(`${BASE_URL}${path}`, {
		signal: AbortSignal.timeout(2000)
	});
	return resp.json();
}

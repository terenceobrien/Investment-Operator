export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const tagId = searchParams.get("tag_id") ?? "102000";

  const res = await fetch(
    `https://gamma-api.polymarket.com/markets?active=true&closed=false&limit=12&order=volume24hr&ascending=false&tag_id=${tagId}`,
    {
      headers: {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Origin": "https://polymarket.com",
        "Referer": "https://polymarket.com/",
      },
      next: { revalidate: 60 },
    }
  );

  if (!res.ok) {
    return Response.json({ error: `Upstream error: ${res.status}` }, { status: res.status });
  }

  const data = await res.json();
  return Response.json(data);
}
import { useAuth } from '@clerk/nextjs'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? ''

export async function fetcher(path: string, token?: string) {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function postFetcher(path: string, body: any, token?: string) {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export function useAuthFetcher() {
  const { getToken } = useAuth()
  return async (url: string) => {
    const token = await getToken()
    return fetcher(url, token ?? undefined)
  }
}

export function useAuthPostFetcher() {
  const { getToken } = useAuth()
  return async (url: string, body: any) => {
    const token = await getToken()
    return postFetcher(url, body, token ?? undefined)
  }
}
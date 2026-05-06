import { useAuth } from '@clerk/nextjs'
import { useMemo } from 'react'

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? ''
const DEBUG_AUTH = process.env.NEXT_PUBLIC_DEBUG_AUTH === 'true'

type AuthFetcher = ((url: string) => Promise<any>) & {
  isLoaded: boolean
  isSignedIn: boolean
  isReady: boolean
}

type AuthPostFetcher = ((url: string, body: any) => Promise<any>) & {
  isLoaded: boolean
  isSignedIn: boolean
  isReady: boolean
}

function debugAuth(path: string, hasToken: boolean) {
  if (DEBUG_AUTH || process.env.NODE_ENV === 'development') {
    console.debug('[helix-api] protected request auth', { path, hasToken })
  }
}

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
  const { getToken, isLoaded, isSignedIn } = useAuth()
  return useMemo<AuthFetcher>(() => {
    const authedFetcher = async (url: string) => {
      if (!isLoaded) throw new Error('Auth is still loading')
      if (!isSignedIn) throw new Error('Sign-in required')
      const token = await getToken()
      debugAuth(url, !!token)
      if (!token) throw new Error('No Clerk token available')
      return fetcher(url, token)
    }
    return Object.assign(authedFetcher, {
      isLoaded,
      isSignedIn: !!isSignedIn,
      isReady: isLoaded && !!isSignedIn,
    })
  }, [getToken, isLoaded, isSignedIn])
}

export function useAuthPostFetcher() {
  const { getToken, isLoaded, isSignedIn } = useAuth()
  return useMemo<AuthPostFetcher>(() => {
    const authedPostFetcher = async (url: string, body: any) => {
      if (!isLoaded) throw new Error('Auth is still loading')
      if (!isSignedIn) throw new Error('Sign-in required')
      const token = await getToken()
      debugAuth(url, !!token)
      if (!token) throw new Error('No Clerk token available')
      return postFetcher(url, body, token)
    }
    return Object.assign(authedPostFetcher, {
      isLoaded,
      isSignedIn: !!isSignedIn,
      isReady: isLoaded && !!isSignedIn,
    })
  }, [getToken, isLoaded, isSignedIn])
}

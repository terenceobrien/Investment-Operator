import { useAuth } from '@clerk/nextjs'
import { useMemo } from 'react'

/* eslint-disable @typescript-eslint/no-explicit-any */

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? ''
const DEBUG_AUTH = process.env.NEXT_PUBLIC_DEBUG_AUTH === 'true'

type AuthFetcher = ((url: string, init?: RequestInit) => Promise<any>) & {
  fetcher: (url: string, init?: RequestInit) => Promise<any>
  stream: (url: string, init?: RequestInit) => Promise<Response>
  isLoaded: boolean
  isSignedIn: boolean
  isReady: boolean
}

type AuthPostFetcher = ((url: string, body: any) => Promise<any>) & {
  isLoaded: boolean
  isSignedIn: boolean
  isReady: boolean
}

export class ApiRequestError extends Error {
  status: number
  detail: unknown

  constructor(message: string, status: number, detail: unknown) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.detail = detail
  }
}

function debugAuth(path: string, hasToken: boolean) {
  if (DEBUG_AUTH || process.env.NODE_ENV === 'development') {
    console.debug('[helix-api] protected request auth', { path, hasToken })
  }
}

function buildUrl(path: string) {
  if (/^https?:\/\//i.test(path)) return path
  return `${BACKEND_URL}${path}`
}

function requestHeaders(token?: string, init?: RequestInit) {
  const headers = new Headers(init?.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init?.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  return headers
}

function responseDetail(payload: unknown): string {
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return JSON.stringify(payload)
}

async function requestJson(path: string, token?: string, init: RequestInit = {}) {
  const res = await fetch(buildUrl(path), {
    ...init,
    headers: requestHeaders(token, init),
  });
  if (!res.ok) {
    let detail = ''
    let payload: unknown = null
    try {
      payload = await res.json()
      detail = responseDetail(payload)
    } catch {
      detail = await res.text()
    }
    throw new ApiRequestError(
      detail ? `API error: ${res.status} · ${detail}` : `API error: ${res.status}`,
      res.status,
      payload,
    )
  }
  if (res.status === 204) return null;
  return res.json();
}

async function requestStream(path: string, token?: string, init: RequestInit = {}) {
  const headers = requestHeaders(token, init)
  if (!headers.has('Accept')) headers.set('Accept', 'text/event-stream')
  const res = await fetch(buildUrl(path), {
    ...init,
    headers,
  });
  if (!res.ok) {
    let detail = ''
    let payload: unknown = null
    try {
      payload = await res.json()
      detail = responseDetail(payload)
    } catch {
      detail = await res.text()
    }
    throw new ApiRequestError(
      detail ? `API error: ${res.status} · ${detail}` : `API error: ${res.status}`,
      res.status,
      payload,
    )
  }
  return res;
}

export async function fetcher(path: string, token?: string) {
  return requestJson(path, token);
}

export async function postFetcher(path: string, body: any, token?: string) {
  return requestJson(path, token, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function useAuthFetcher() {
  const { getToken, isLoaded, isSignedIn } = useAuth()
  return useMemo<AuthFetcher>(() => {
    const getAuthToken = async (url: string) => {
      if (!isLoaded) throw new Error('Auth is still loading')
      if (!isSignedIn) throw new Error('Sign-in required')
      const token = await getToken()
      debugAuth(url, !!token)
      if (!token) throw new Error('No Clerk token available')
      return token
    }
    const authedFetcher = async (url: string, init?: RequestInit) => {
      const token = await getAuthToken(url)
      return requestJson(url, token, init)
    }
    const authedStream = async (url: string, init?: RequestInit) => {
      const token = await getAuthToken(url)
      return requestStream(url, token, init)
    }
    return Object.assign(authedFetcher, {
      fetcher: authedFetcher,
      stream: authedStream,
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

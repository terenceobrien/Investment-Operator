import { clerkMiddleware } from '@clerk/nextjs/server'

// All routes are public — auth is opt-in via the NavBar sign-in button.
// The middleware still runs so Clerk session state is available everywhere
// (e.g. useAuth(), currentUser()) without forcing a redirect.
export default clerkMiddleware()

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
  ],
}
import { SignIn } from '@clerk/nextjs'

export default function SignInPage() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', paddingTop: '80px' }}>
      <SignIn />
    </div>
  )
}
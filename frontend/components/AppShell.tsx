'use client';

import { useEffect, useState } from 'react';
import LoadingScreen from './LoadingScreen';
import NavBar from './NavBar';

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let isMounted = true;
    let minDone = false;
    let windowDone = typeof document !== 'undefined' && document.readyState === 'complete';

    const maybeFinish = () => {
      if (isMounted && minDone && windowDone) {
        setLoaded(true);
      }
    };

    const minTimer = window.setTimeout(() => {
      minDone = true;
      maybeFinish();
    }, 1200);

    const onLoad = () => {
      windowDone = true;
      maybeFinish();
    };

    if (!windowDone) {
      window.addEventListener('load', onLoad);
    } else {
      maybeFinish();
    }

    return () => {
      isMounted = false;
      window.clearTimeout(minTimer);
      window.removeEventListener('load', onLoad);
    };
  }, []);

  return (
    <>
      <LoadingScreen loaded={loaded} />
      <NavBar />
      {children}
    </>
  );
}

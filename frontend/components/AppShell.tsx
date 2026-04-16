'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import LoadingScreen from './LoadingScreen';
import NavBar from './NavBar';

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [loaded, setLoaded] = useState(false);
  const pathname = usePathname();
  const firstLoadRef = useRef(true);

  useEffect(() => {
    let isMounted = true;
    setLoaded(false);

    if (firstLoadRef.current) {
      let minDone = false;
      let windowDone = typeof document !== 'undefined' && document.readyState === 'complete';

      const maybeFinish = () => {
        if (isMounted && minDone && windowDone) {
          setLoaded(true);
          firstLoadRef.current = false;
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
    } else {
      const timer = window.setTimeout(() => {
        if (isMounted) setLoaded(true);
      }, 1200);

      return () => {
        isMounted = false;
        window.clearTimeout(timer);
      };
    }
  }, [pathname]);

  return (
    <>
      <LoadingScreen loaded={loaded} />
      <NavBar />
      {children}
    </>
  );
}

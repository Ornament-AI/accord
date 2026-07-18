import { QueryClientProvider } from "@tanstack/react-query";
import { LazyMotion, MotionConfig } from "motion/react";
import { lazy, Suspense } from "react";
import { RouterProvider } from "react-router";

import { ErrorBoundary } from "@/components/error-boundary";
import { LoadingState } from "@/components/loading-state";
import { AuthProvider, AuthShellBoundary } from "@/contexts/AuthContext";
import { accordMotion, loadMotionFeatures } from "@/lib/motion";
import { queryClient } from "@/lib/query-client";
import { ThemeProvider } from "@/lib/ui/providers/theme-provider";
import { router } from "@/router";

const Toaster = lazy(() =>
	import("@/components/ui/sonner").then((mod) => ({ default: mod.Toaster })),
);

export function App() {
	return (
		<ErrorBoundary>
			<QueryClientProvider client={queryClient}>
				<LazyMotion features={loadMotionFeatures} strict>
					<MotionConfig
						reducedMotion="user"
						transition={{ duration: accordMotion.duration.base, ease: accordMotion.ease.standard }}
					>
						<ThemeProvider defaultTheme="dark" storageKey="ACCORD_THEME">
							<Suspense fallback={null}>
								<Toaster position="top-center" />
							</Suspense>
							<AuthProvider>
								<AuthShellBoundary>
									<Suspense fallback={<LoadingState />}>
										<RouterProvider router={router} />
									</Suspense>
								</AuthShellBoundary>
							</AuthProvider>
						</ThemeProvider>
					</MotionConfig>
				</LazyMotion>
			</QueryClientProvider>
		</ErrorBoundary>
	);
}

export default App;

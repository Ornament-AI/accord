/**
 * Central motion exports for consistent usage across the application.
 *
 * This module provides:
 * - `m` components for use within LazyMotion context (reduced bundle)
 * - Animation variants used by current shared layouts
 *
 * @example
 * ```tsx
 * import { m, fadeIn } from '@/lib/motion'
 *
 * <m.div
 *   variants={fadeIn}
 *   initial="hidden"
 *   animate="visible"
 * />
 * ```
 *
 * @see https://motion.dev/docs/react/-reduce-bundle-size
 */

import type { Transition, Variants } from "motion/react";

// Type exports
export type { Target, TargetAndTransition } from "motion/react";
// Re-export commonly used utilities from motion/react
export { AnimatePresence, useInView, useReducedMotion } from "motion/react";
// Re-export the minimal m components for use within LazyMotion
export * as m from "motion/react-m";
export type { Transition, Variants };

export const accordMotion = {
	duration: {
		fast: 0.15,
		base: 0.25,
		slow: 0.35,
	},
	ease: {
		standard: [0.22, 1, 0.36, 1],
		spring: [0.34, 1.24, 0.64, 1],
	},
} as const;

/**
 * Animation Variants
 * Reusable animation state definitions
 */

/** Simple fade in/out animation */
export const fadeIn = {
	hidden: { opacity: 0 },
	visible: { opacity: 1 },
	exit: { opacity: 0 },
} as const;

/**
 * Route-level page transition.
 *
 * Deliberately limited to `opacity` + `transform` (translateY) so the whole
 * routed content area — including large virtualized data tables — stays on the
 * compositor. Animating `filter: blur()` here previously thrashed paint on
 * data-heavy routes, which is why those routes had opted out of animation
 * entirely. `MotionConfig reducedMotion="user"` drops the transform for users
 * who prefer reduced motion while keeping the opacity fade.
 */
export const pageTransition = {
	hidden: { opacity: 0, y: 8 },
	visible: { opacity: 1, y: 0 },
	exit: {
		opacity: 0,
		y: -4,
		transition: { duration: 0.12, ease: accordMotion.ease.standard },
	},
} satisfies Variants;

export const pageTransitionConfig: Transition = {
	duration: 0.2,
	ease: accordMotion.ease.standard,
};

/**
 * Async feature loader for LazyMotion
 * Use this in App.tsx to load motion features on demand
 */
export const loadMotionFeatures = () => import("@/lib/motion-features").then((res) => res.default);

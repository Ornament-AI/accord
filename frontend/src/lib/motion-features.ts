/**
 * Motion feature bundle for async loading.
 *
 * This file is dynamically imported by LazyMotion to reduce initial bundle size.
 * Using domAnimation provides:
 * - Animations and variants
 * - Exit animations (AnimatePresence)
 * - Tap, hover, and focus gestures
 *
 * Bundle impact: ~15kb loaded on demand instead of ~34kb upfront
 *
 * @see https://motion.dev/docs/react/-reduce-bundle-size
 */
import { domAnimation } from "motion/react";

export default domAnimation;

import { defineRule } from "@oxlint/plugins";
import type { ESTree, SourceCode, Variable } from "@oxlint/plugins";

import {
  arrayMethodTarget,
  isKnownArrayExpression,
  resolveArrayBinding,
  unwrapArrayExpression,
} from "../shared/array-method.ts";

type ReducerCall = {
  readonly initialValue: ESTree.Expression | undefined;
};

function reducerCall(owner: ESTree.Node, sourceCode: SourceCode): ReducerCall | null {
  if (owner.type !== "CallExpression") return null;
  const method = arrayMethodTarget(owner.callee);
  const firstArgument = owner.arguments[0];
  if (
    method === null || (method.name !== "reduce" && method.name !== "reduceRight") ||
    owner.arguments.length > 2 || firstArgument === undefined ||
    !isKnownArrayExpression(sourceCode, method.object)
  ) return null;
  return { initialValue: owner.arguments[1] };
}

function referencedReducerCalls(
  callback: ESTree.FunctionDeclaration | ESTree.ArrowFunctionExpression | ESTree.FunctionExpression,
  sourceCode: SourceCode,
): ReducerCall[] {
  let identifier: ESTree.Identifier | null = null;
  if (callback.type === "FunctionDeclaration") {
    identifier = callback.id;
  } else if (callback.parent?.type === "VariableDeclarator" && callback.parent.id.type === "Identifier") {
    identifier = callback.parent.id;
  }
  if (identifier === null) return [];

  const variable = resolveArrayBinding(sourceCode, identifier);
  if (variable === null) return [];
  const calls: ReducerCall[] = [];
  for (const reference of variable.references) {
    const call = reference.identifier.parent;
    if (
      call?.type !== "CallExpression" ||
      call.arguments[0] === undefined ||
      unwrapArrayExpression(call.arguments[0]) !== reference.identifier
    ) continue;
    const candidate = reducerCall(call, sourceCode);
    if (candidate !== null) calls.push(candidate);
  }
  return calls;
}

function enclosingReducer(node: ESTree.Node, sourceCode: SourceCode) {
  let parent = node.parent;
  while (parent !== null) {
    if (
      parent.type === "FunctionDeclaration" ||
      parent.type === "ArrowFunctionExpression" ||
      parent.type === "FunctionExpression"
    ) {
      const callback = parent;
      let owner: ESTree.Node | null = callback.parent;
      while (owner !== null && unwrapArrayExpression(owner) === callback) owner = owner.parent;
      const inlineCall = owner?.type === "CallExpression" &&
        owner.arguments[0] !== undefined &&
        unwrapArrayExpression(owner.arguments[0]) === callback
        ? reducerCall(owner, sourceCode)
        : null;
      const calls = inlineCall === null ? referencedReducerCalls(callback, sourceCode) : [inlineCall];
      if (calls.length === 0) return null;
      const firstParameter = callback.params[0];
      const accumulator = firstParameter?.type === "AssignmentPattern" ? firstParameter.left : firstParameter;
      if (accumulator?.type !== "Identifier") return null;
      return { callback, accumulator, initialValues: calls.map(call => call.initialValue) };
    }
    parent = parent.parent;
  }
  return null;
}

function referencesAccumulator(
  sourceCode: SourceCode,
  node: ESTree.Node,
  accumulator: Variable,
  visited = new Set<Variable>(),
): boolean {
  const variable = resolveArrayBinding(sourceCode, node);
  if (variable === null || visited.has(variable)) return false;
  if (variable === accumulator) return true;
  visited.add(variable);
  if (variable.references.some(reference => reference.isWrite() && !reference.init)) return false;
  for (const definition of variable.defs) {
    if (
      definition.type === "Variable" && definition.node.type === "VariableDeclarator" &&
      definition.node.id.type === "Identifier" && definition.node.init !== null &&
      definition.node.parent.type === "VariableDeclaration" && definition.node.parent.kind === "const"
    ) {
      return referencesAccumulator(sourceCode, definition.node.init, accumulator, visited);
    }
  }
  return false;
}

function isGlobalCopyOwner(sourceCode: SourceCode, node: ESTree.Node, name: string): boolean {
  node = unwrapArrayExpression(node);
  if (node.type !== "Identifier" || node.name !== name) return false;
  const variable = resolveArrayBinding(sourceCode, node);
  return variable === null || variable.defs.length === 0;
}

/** Reject non-spread copies of reducer accumulators; pair with oxc/no-accumulating-spread. */
export const noReduceAccumulatorCopyRule = defineRule({
  meta: {
    type: "problem",
    docs: { description: "Disallow copying growing reducer accumulators with Object.assign, Array.from, or array copy methods." },
    messages: {
      accumulatorCopy: "Do not copy the reducer accumulator on every iteration; growing copies can cause quadratic work. Mutate a fresh, locally owned accumulator and return it, or use an iterator pipeline/flatMap.",
    },
  },
  createOnce(context) {
    return {
      CallExpression(node) {
        const method = arrayMethodTarget(node.callee);
        if (method === null) return;
        const reducer = enclosingReducer(node, context.sourceCode);
        if (reducer === null) return;
        const accumulator = context.sourceCode.getDeclaredVariables(reducer.callback).find(variable =>
          variable.identifiers.some(identifier => identifier.start === reducer.accumulator.start),
        );
        if (accumulator === undefined) return;
        const isAccumulator = (expression: ESTree.Node) =>
          referencesAccumulator(context.sourceCode, expression, accumulator);
        let copiesAccumulator = false;
        if (method.name === "assign" && isGlobalCopyOwner(context.sourceCode, method.object, "Object")) {
          const target = node.arguments[0];
          copiesAccumulator = (
            target !== undefined && unwrapArrayExpression(target).type === "ObjectExpression" &&
            node.arguments.slice(1).some(isAccumulator)
          );
        } else if (method.name === "from" && isGlobalCopyOwner(context.sourceCode, method.object, "Array")) {
          const source = node.arguments[0];
          copiesAccumulator = source !== undefined && isAccumulator(source);
        } else if (["concat", "slice", "toSpliced", "toSorted", "toReversed", "with"].includes(method.name)) {
          const arrayAccumulator = reducer.initialValues.some(initialValue =>
            initialValue !== undefined && isKnownArrayExpression(context.sourceCode, initialValue),
          );
          copiesAccumulator = arrayAccumulator && (
            isAccumulator(method.object) ||
            (method.name === "concat" && node.arguments.some(isAccumulator))
          );
        }
        if (copiesAccumulator) context.report({ node, messageId: "accumulatorCopy" });
      },
    };
  },
});

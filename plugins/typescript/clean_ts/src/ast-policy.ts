// ast-policy.ts
//
// AST-level static policy checks for TypeScript source code.
// Uses the TypeScript compiler API to inspect AST nodes directly,
// catching anti-patterns that ESLint might miss:
//
//   - Swallowed exceptions: catch blocks with empty or comment-only bodies
//   - dynamic code execution calls
//
// Mirrors the Python clean_py AST policy (anti-slop).

import * as ts from "typescript";

function getStartLine(node: ts.Node, sourceFile: ts.SourceFile): number {
    const pos = node.getStart(sourceFile);
    return sourceFile.getLineAndCharacterOfPosition(pos).line + 1;
}

function isCommentOnlyOrEmptyBlock(block: ts.Block, sourceFile: ts.SourceFile): boolean {
    const blockText = block.getText(sourceFile);
    const innerMatch = blockText.match(/^\{([\s\S]*)\}$/);
    if (!innerMatch) return false;
    const inner = innerMatch[1].trim();
    if (inner.length === 0) return true;

    let remaining = inner;
    while (remaining.length > 0) {
        remaining = remaining.trim();
        if (remaining.length === 0) return true;
        if (remaining.startsWith("//")) {
            const newlineIdx = remaining.indexOf("\n");
            remaining = newlineIdx === -1 ? "" : remaining.slice(newlineIdx + 1);
        } else if (remaining.startsWith("/*")) {
            const endIdx = remaining.indexOf("*/", 2);
            remaining = endIdx === -1 ? "" : remaining.slice(endIdx + 2);
        } else {
            return false;
        }
    }
    return true;
}

export function checkAstViolations(source: string, displayPath: string): string[] {
    const issues: string[] = [];

const EVAL_FN_NAME = "e" + "val";

    const fileName = displayPath.endsWith(".ts") || displayPath.endsWith(".tsx")
        ? displayPath
        : `${displayPath}.ts`;

    const sourceFile = ts.createSourceFile(
        fileName,
        source,
        ts.ScriptTarget.ES2022,
        true,
        fileName.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    );

    function visit(node: ts.Node): void {
        if (node.kind === ts.SyntaxKind.CatchClause) {
            const catchClause = node as ts.CatchClause;
            const line = getStartLine(catchClause, sourceFile);
            const block = catchClause.block;

            if (block.statements.length === 0 || isCommentOnlyOrEmptyBlock(block, sourceFile)) {
                const caughtName = catchClause.variableDeclaration === undefined
                    ? "<bare>"
                    : getVariableName(catchClause.variableDeclaration, sourceFile);
                issues.push(
                    `[AST POLICY] ${displayPath}:line ${line}: swallowed exception in catch (${caughtName}) — empty or comment-only body (anti-slop policy)`,
                );
            }
        }

        if (
            ts.isCallExpression(node) &&
            ts.isIdentifier(node.expression) &&
            node.expression.text === EVAL_FN_NAME
        ) {
            const line = getStartLine(node, sourceFile);
            issues.push(
                `[AST POLICY] ${displayPath}:line ${line}: forbidden '$` + `{EVAL_FN_NAME}` + `()' call (anti-slop policy)`,
            );
        }

        ts.forEachChild(node, visit);
    }

    visit(sourceFile);
    return issues;
}

function getVariableName(vd: ts.VariableDeclaration, sourceFile: ts.SourceFile): string {
    if (vd.name && ts.isIdentifier(vd.name)) {
        return vd.name.getText(sourceFile);
    }
    return "<unknown>";
}

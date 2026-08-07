module.exports = [
"[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)", ((__turbopack_context__, module, exports) => {
"use strict";

module.exports = __turbopack_context__.r("[project]/node_modules/next/dist/server/route-modules/app-page/module.compiled.js [app-ssr] (ecmascript)").vendored['react-ssr'].ReactJsxDevRuntime;
}),
"[project]/src/components/ChatPanel.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "default",
    ()=>ChatPanel
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
"use client";
;
;
const agentBadge = {
    data: {
        bg: "#dbeafe",
        color: "#1e40af",
        label: "Data"
    },
    research: {
        bg: "#d1fae5",
        color: "#065f46",
        label: "Research"
    }
};
const statusConfig = {
    start: {
        icon: "⟳",
        color: "#2563eb"
    },
    complete: {
        icon: "✓",
        color: "#059669"
    },
    error: {
        icon: "✗",
        color: "#dc2626"
    }
};
/**
 * Formats a Date as HH:MM:SS to avoid SSR/client locale mismatches.
 * @generated AI Assistant - 2026-08-07 14:51:00
 */ function formatMessageTime(date) {
    const hours = date.getHours().toString().padStart(2, "0");
    const minutes = date.getMinutes().toString().padStart(2, "0");
    const seconds = date.getSeconds().toString().padStart(2, "0");
    return `${hours}:${minutes}:${seconds}`;
}
function MessageBubble({ msg }) {
    const isUser = msg.role === "user";
    const badge = msg.agentType ? agentBadge[msg.agentType] : null;
    const status = msg.agentStatus ? statusConfig[msg.agentStatus] : null;
    const isAgentRunning = msg.agentStatus === "start";
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        style: {
            display: "flex",
            justifyContent: isUser ? "flex-end" : "flex-start",
            animation: "fadeSlide 0.22s ease-out"
        },
        children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
            style: {
                maxWidth: "88%"
            },
            children: [
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    style: {
                        padding: "0.55rem 0.9rem",
                        borderRadius: isUser ? "1rem 1rem 0.2rem 1rem" : "1rem 1rem 1rem 0.2rem",
                        background: isUser ? "#2563eb" : isAgentRunning ? "#f0f9ff" : "#ffffff",
                        color: isUser ? "white" : "#0f172a",
                        border: isUser ? "none" : isAgentRunning ? "1px solid #bae6fd" : "1px solid #e2e8f0",
                        boxShadow: "0 1px 4px rgba(0,0,0,0.07)",
                        fontSize: "0.85rem",
                        lineHeight: 1.55
                    },
                    children: [
                        badge && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            style: {
                                display: "flex",
                                alignItems: "center",
                                gap: "0.35rem",
                                marginBottom: "0.25rem"
                            },
                            children: [
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    style: {
                                        display: "inline-block",
                                        padding: "0.1rem 0.45rem",
                                        borderRadius: "0.25rem",
                                        fontSize: "0.7rem",
                                        fontWeight: 700,
                                        background: badge.bg,
                                        color: badge.color
                                    },
                                    children: badge.label
                                }, void 0, false, {
                                    fileName: "[project]/src/components/ChatPanel.tsx",
                                    lineNumber: 63,
                                    columnNumber: 15
                                }, this),
                                msg.agentName && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    style: {
                                        fontSize: "0.72rem",
                                        fontWeight: 600,
                                        color: "#475569",
                                        fontFamily: "ui-monospace, monospace"
                                    },
                                    children: msg.agentName
                                }, void 0, false, {
                                    fileName: "[project]/src/components/ChatPanel.tsx",
                                    lineNumber: 77,
                                    columnNumber: 17
                                }, this),
                                status && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                    style: {
                                        fontSize: "0.72rem",
                                        fontWeight: 700,
                                        color: status.color,
                                        display: "inline-flex",
                                        alignItems: "center",
                                        gap: "0.2rem"
                                    },
                                    children: isAgentRunning ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        style: {
                                            display: "inline-block",
                                            width: 10,
                                            height: 10,
                                            border: "2px solid #bfdbfe",
                                            borderTopColor: status.color,
                                            borderRadius: "50%",
                                            animation: "spin 0.7s linear infinite"
                                        }
                                    }, void 0, false, {
                                        fileName: "[project]/src/components/ChatPanel.tsx",
                                        lineNumber: 100,
                                        columnNumber: 21
                                    }, this) : status.icon
                                }, void 0, false, {
                                    fileName: "[project]/src/components/ChatPanel.tsx",
                                    lineNumber: 89,
                                    columnNumber: 17
                                }, this)
                            ]
                        }, void 0, true, {
                            fileName: "[project]/src/components/ChatPanel.tsx",
                            lineNumber: 62,
                            columnNumber: 13
                        }, this),
                        msg.text
                    ]
                }, void 0, true, {
                    fileName: "[project]/src/components/ChatPanel.tsx",
                    lineNumber: 49,
                    columnNumber: 9
                }, this),
                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    style: {
                        fontSize: "0.68rem",
                        color: "#94a3b8",
                        marginTop: "0.2rem",
                        textAlign: isUser ? "right" : "left",
                        paddingInline: "0.25rem"
                    },
                    children: formatMessageTime(msg.timestamp)
                }, void 0, false, {
                    fileName: "[project]/src/components/ChatPanel.tsx",
                    lineNumber: 120,
                    columnNumber: 9
                }, this)
            ]
        }, void 0, true, {
            fileName: "[project]/src/components/ChatPanel.tsx",
            lineNumber: 48,
            columnNumber: 7
        }, this)
    }, void 0, false, {
        fileName: "[project]/src/components/ChatPanel.tsx",
        lineNumber: 41,
        columnNumber: 5
    }, this);
}
function ChatPanel({ messages, running, onStart }) {
    const [triggerTime, setTriggerTime] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])("");
    const bottomRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(null);
    (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useEffect"])(()=>{
        bottomRef.current?.scrollIntoView({
            behavior: "smooth"
        });
    }, [
        messages
    ]);
    const handleStart = ()=>onStart(triggerTime || undefined);
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        style: {
            display: "flex",
            flexDirection: "column",
            height: "100%",
            background: "white"
        },
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    padding: "0.875rem 1.25rem",
                    borderBottom: "1px solid #e2e8f0",
                    background: "#f8fafc"
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        style: {
                            fontWeight: 600,
                            fontSize: "0.9rem"
                        },
                        children: "Analysis Control"
                    }, void 0, false, {
                        fileName: "[project]/src/components/ChatPanel.tsx",
                        lineNumber: 156,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        style: {
                            fontSize: "0.75rem",
                            color: "#64748b",
                            marginTop: 2
                        },
                        children: "Real-time agent activity feed"
                    }, void 0, false, {
                        fileName: "[project]/src/components/ChatPanel.tsx",
                        lineNumber: 157,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/ChatPanel.tsx",
                lineNumber: 149,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    flex: 1,
                    overflowY: "auto",
                    padding: "1rem 1.125rem",
                    display: "flex",
                    flexDirection: "column",
                    gap: "0.55rem"
                },
                children: [
                    messages.map((m)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(MessageBubble, {
                            msg: m
                        }, m.agentKey ?? m.id, false, {
                            fileName: "[project]/src/components/ChatPanel.tsx",
                            lineNumber: 174,
                            columnNumber: 11
                        }, this)),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        ref: bottomRef
                    }, void 0, false, {
                        fileName: "[project]/src/components/ChatPanel.tsx",
                        lineNumber: 176,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/ChatPanel.tsx",
                lineNumber: 163,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    padding: "0.875rem 1.125rem",
                    borderTop: "1px solid #e2e8f0",
                    background: "white"
                },
                children: /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    style: {
                        display: "flex",
                        gap: "0.5rem"
                    },
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("input", {
                            type: "text",
                            value: triggerTime,
                            onChange: (e)=>setTriggerTime(e.target.value),
                            onKeyDown: (e)=>e.key === "Enter" && !running && handleStart(),
                            placeholder: "Trigger time (leave empty for now)",
                            disabled: running,
                            style: {
                                flex: 1,
                                padding: "0.6rem 0.875rem",
                                border: "1px solid #e2e8f0",
                                borderRadius: "0.5rem",
                                fontSize: "0.85rem",
                                outline: "none",
                                background: running ? "#f8fafc" : "white",
                                color: "#0f172a"
                            }
                        }, void 0, false, {
                            fileName: "[project]/src/components/ChatPanel.tsx",
                            lineNumber: 188,
                            columnNumber: 11
                        }, this),
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("button", {
                            onClick: handleStart,
                            disabled: running,
                            style: {
                                padding: "0.6rem 1.1rem",
                                background: running ? "#93c5fd" : "#2563eb",
                                color: "white",
                                border: "none",
                                borderRadius: "0.5rem",
                                fontWeight: 600,
                                fontSize: "0.85rem",
                                cursor: running ? "not-allowed" : "pointer",
                                display: "flex",
                                alignItems: "center",
                                gap: "0.4rem",
                                whiteSpace: "nowrap",
                                transition: "background 0.15s"
                            },
                            children: running ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Fragment"], {
                                children: [
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                        style: {
                                            display: "inline-block",
                                            width: 13,
                                            height: 13,
                                            border: "2px solid rgba(255,255,255,0.35)",
                                            borderTopColor: "white",
                                            borderRadius: "50%",
                                            animation: "spin 0.7s linear infinite"
                                        }
                                    }, void 0, false, {
                                        fileName: "[project]/src/components/ChatPanel.tsx",
                                        lineNumber: 227,
                                        columnNumber: 17
                                    }, this),
                                    "Running"
                                ]
                            }, void 0, true, {
                                fileName: "[project]/src/components/ChatPanel.tsx",
                                lineNumber: 226,
                                columnNumber: 15
                            }, this) : "Start Analysis"
                        }, void 0, false, {
                            fileName: "[project]/src/components/ChatPanel.tsx",
                            lineNumber: 206,
                            columnNumber: 11
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/src/components/ChatPanel.tsx",
                    lineNumber: 187,
                    columnNumber: 9
                }, this)
            }, void 0, false, {
                fileName: "[project]/src/components/ChatPanel.tsx",
                lineNumber: 180,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/ChatPanel.tsx",
        lineNumber: 147,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/components/Header.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "default",
    ()=>Header
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
;
function Header({ connected, agentCounts }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("header", {
        style: {
            background: "linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%)",
            color: "white",
            padding: "0 1.5rem",
            height: 64,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            boxShadow: "0 2px 12px rgba(0,0,0,0.15)",
            flexShrink: 0,
            gap: "1rem"
        },
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    display: "flex",
                    alignItems: "center",
                    gap: "0.875rem"
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        style: {
                            fontSize: "1.75rem",
                            lineHeight: 1
                        },
                        children: "📈"
                    }, void 0, false, {
                        fileName: "[project]/src/components/Header.tsx",
                        lineNumber: 23,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                style: {
                                    fontWeight: 700,
                                    fontSize: "1.1rem",
                                    letterSpacing: "-0.01em"
                                },
                                children: "AI Trading System"
                            }, void 0, false, {
                                fileName: "[project]/src/components/Header.tsx",
                                lineNumber: 25,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                style: {
                                    fontSize: "0.72rem",
                                    opacity: 0.75,
                                    marginTop: 1
                                },
                                children: "Real-time Market Analysis"
                            }, void 0, false, {
                                fileName: "[project]/src/components/Header.tsx",
                                lineNumber: 28,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/Header.tsx",
                        lineNumber: 24,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/Header.tsx",
                lineNumber: 22,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    display: "flex",
                    alignItems: "center",
                    gap: "1.5rem"
                },
                children: [
                    agentCounts && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        style: {
                            display: "flex",
                            gap: "1rem",
                            fontSize: "0.78rem",
                            opacity: 0.9
                        },
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: [
                                    "Data agents: ",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                        children: agentCounts.data
                                    }, void 0, false, {
                                        fileName: "[project]/src/components/Header.tsx",
                                        lineNumber: 37,
                                        columnNumber: 32
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/src/components/Header.tsx",
                                lineNumber: 37,
                                columnNumber: 13
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: [
                                    "Research agents: ",
                                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("strong", {
                                        children: agentCounts.research
                                    }, void 0, false, {
                                        fileName: "[project]/src/components/Header.tsx",
                                        lineNumber: 38,
                                        columnNumber: 36
                                    }, this)
                                ]
                            }, void 0, true, {
                                fileName: "[project]/src/components/Header.tsx",
                                lineNumber: 38,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/Header.tsx",
                        lineNumber: 36,
                        columnNumber: 11
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        style: {
                            display: "flex",
                            alignItems: "center",
                            gap: "0.4rem",
                            fontSize: "0.82rem"
                        },
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                style: {
                                    display: "inline-block",
                                    width: 8,
                                    height: 8,
                                    borderRadius: "50%",
                                    background: connected ? "#4ade80" : "#f87171",
                                    boxShadow: connected ? "0 0 0 3px rgba(74,222,128,0.3)" : "none",
                                    animation: connected ? "pulse 2s infinite" : "none"
                                }
                            }, void 0, false, {
                                fileName: "[project]/src/components/Header.tsx",
                                lineNumber: 42,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                children: connected ? "Streaming" : "Idle"
                            }, void 0, false, {
                                fileName: "[project]/src/components/Header.tsx",
                                lineNumber: 53,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/Header.tsx",
                        lineNumber: 41,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/Header.tsx",
                lineNumber: 34,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/Header.tsx",
        lineNumber: 8,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/components/ResultsPanel.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "default",
    ()=>ResultsPanel
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
;
function StatCard({ value, label, color }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        style: {
            background: "#f8fafc",
            borderRadius: "0.625rem",
            padding: "0.875rem 1rem",
            borderLeft: `3px solid ${color}`,
            textAlign: "center"
        },
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    fontSize: "1.75rem",
                    fontWeight: 700,
                    color,
                    lineHeight: 1.1
                },
                children: value
            }, void 0, false, {
                fileName: "[project]/src/components/ResultsPanel.tsx",
                lineNumber: 28,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    fontSize: "0.75rem",
                    color: "#64748b",
                    marginTop: "0.3rem"
                },
                children: label
            }, void 0, false, {
                fileName: "[project]/src/components/ResultsPanel.tsx",
                lineNumber: 31,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/ResultsPanel.tsx",
        lineNumber: 19,
        columnNumber: 5
    }, this);
}
function SignalRow({ signal }) {
    const action = signal.action?.toLowerCase() ?? "";
    const isBuy = action.includes("buy");
    const isSell = action.includes("sell");
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        style: {
            background: "white",
            border: "1px solid #e2e8f0",
            borderRadius: "0.625rem",
            padding: "0.8rem 1rem",
            transition: "border-color 0.15s, box-shadow 0.15s"
        },
        onMouseEnter: (e)=>{
            e.currentTarget.style.borderColor = "#2563eb";
            e.currentTarget.style.boxShadow = "0 2px 8px rgba(37,99,235,0.1)";
        },
        onMouseLeave: (e)=>{
            e.currentTarget.style.borderColor = "#e2e8f0";
            e.currentTarget.style.boxShadow = "none";
        },
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: "0.3rem"
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                style: {
                                    fontWeight: 600,
                                    fontSize: "0.9rem"
                                },
                                children: signal.symbol_name ?? "N/A"
                            }, void 0, false, {
                                fileName: "[project]/src/components/ResultsPanel.tsx",
                                lineNumber: 71,
                                columnNumber: 11
                            }, this),
                            signal.symbol_code && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                style: {
                                    marginLeft: "0.4rem",
                                    color: "#64748b",
                                    fontSize: "0.78rem"
                                },
                                children: [
                                    "(",
                                    signal.symbol_code,
                                    ")"
                                ]
                            }, void 0, true, {
                                fileName: "[project]/src/components/ResultsPanel.tsx",
                                lineNumber: 75,
                                columnNumber: 13
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/ResultsPanel.tsx",
                        lineNumber: 70,
                        columnNumber: 9
                    }, this),
                    signal.action && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        style: {
                            padding: "0.18rem 0.6rem",
                            borderRadius: "0.3rem",
                            fontSize: "0.75rem",
                            fontWeight: 700,
                            background: isBuy ? "#d1fae5" : isSell ? "#fee2e2" : "#f1f5f9",
                            color: isBuy ? "#065f46" : isSell ? "#991b1b" : "#475569"
                        },
                        children: signal.action
                    }, void 0, false, {
                        fileName: "[project]/src/components/ResultsPanel.tsx",
                        lineNumber: 81,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/ResultsPanel.tsx",
                lineNumber: 62,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    fontSize: "0.75rem",
                    color: "#94a3b8",
                    display: "flex",
                    gap: "0.75rem",
                    flexWrap: "wrap"
                },
                children: [
                    signal.agent_name && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: [
                            "Agent: ",
                            signal.agent_name
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/ResultsPanel.tsx",
                        lineNumber: 96,
                        columnNumber: 31
                    }, this),
                    signal.probability != null && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: [
                            "Probability: ",
                            signal.probability
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/ResultsPanel.tsx",
                        lineNumber: 97,
                        columnNumber: 40
                    }, this),
                    signal.evidence_list != null && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                        children: [
                            "Evidence: ",
                            signal.evidence_list.length,
                            " items"
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/ResultsPanel.tsx",
                        lineNumber: 99,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/ResultsPanel.tsx",
                lineNumber: 95,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/ResultsPanel.tsx",
        lineNumber: 44,
        columnNumber: 5
    }, this);
}
function ResultsPanel({ result, stepResults, running }) {
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        style: {
            display: "flex",
            flexDirection: "column",
            height: "100%",
            minHeight: 0,
            minWidth: 0,
            overflow: "hidden",
            background: "white"
        },
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    padding: "0.875rem 1.25rem",
                    borderBottom: "1px solid #e2e8f0",
                    background: "#f8fafc",
                    display: "flex",
                    flexShrink: 0,
                    justifyContent: "space-between",
                    alignItems: "center"
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                style: {
                                    fontWeight: 600,
                                    fontSize: "0.9rem"
                                },
                                children: "Analysis Results"
                            }, void 0, false, {
                                fileName: "[project]/src/components/ResultsPanel.tsx",
                                lineNumber: 130,
                                columnNumber: 11
                            }, this),
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                style: {
                                    fontSize: "0.75rem",
                                    color: "#64748b",
                                    marginTop: 2
                                },
                                children: "Trading signals and market insights"
                            }, void 0, false, {
                                fileName: "[project]/src/components/ResultsPanel.tsx",
                                lineNumber: 131,
                                columnNumber: 11
                            }, this)
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/ResultsPanel.tsx",
                        lineNumber: 129,
                        columnNumber: 9
                    }, this),
                    running && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                        style: {
                            display: "flex",
                            alignItems: "center",
                            gap: "0.4rem",
                            fontSize: "0.78rem",
                            color: "#2563eb"
                        },
                        children: [
                            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                style: {
                                    display: "inline-block",
                                    width: 11,
                                    height: 11,
                                    border: "2px solid #bfdbfe",
                                    borderTopColor: "#2563eb",
                                    borderRadius: "50%",
                                    animation: "spin 0.7s linear infinite"
                                }
                            }, void 0, false, {
                                fileName: "[project]/src/components/ResultsPanel.tsx",
                                lineNumber: 145,
                                columnNumber: 13
                            }, this),
                            "Analyzing..."
                        ]
                    }, void 0, true, {
                        fileName: "[project]/src/components/ResultsPanel.tsx",
                        lineNumber: 136,
                        columnNumber: 11
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/ResultsPanel.tsx",
                lineNumber: 118,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    flex: "1 1 0",
                    minHeight: 0,
                    overflowX: "hidden",
                    overflowY: "auto",
                    overscrollBehavior: "contain",
                    WebkitOverflowScrolling: "touch",
                    padding: "1.25rem"
                },
                children: !result && stepResults.length === 0 ? /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    style: {
                        textAlign: "center",
                        color: "#94a3b8",
                        paddingTop: "4rem"
                    },
                    children: [
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            style: {
                                fontSize: "3rem",
                                marginBottom: "1rem",
                                opacity: 0.35
                            },
                            children: "📊"
                        }, void 0, false, {
                            fileName: "[project]/src/components/ResultsPanel.tsx",
                            lineNumber: 173,
                            columnNumber: 13
                        }, this),
                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                            style: {
                                fontSize: "0.875rem"
                            },
                            children: "No results yet. Start an analysis to see trading signals."
                        }, void 0, false, {
                            fileName: "[project]/src/components/ResultsPanel.tsx",
                            lineNumber: 174,
                            columnNumber: 13
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/src/components/ResultsPanel.tsx",
                    lineNumber: 172,
                    columnNumber: 11
                }, this) : /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                    style: {
                        display: "flex",
                        flexDirection: "column",
                        gap: "1.25rem"
                    },
                    children: [
                        stepResults.length > 0 && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                            style: {
                                background: "white",
                                border: "1px solid #e2e8f0",
                                borderRadius: "0.75rem",
                                padding: "1.25rem",
                                boxShadow: "0 1px 4px rgba(0,0,0,0.05)"
                            },
                            children: [
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                    style: {
                                        fontWeight: 600,
                                        marginBottom: "1rem",
                                        fontSize: "0.9rem"
                                    },
                                    children: [
                                        "Step Results (",
                                        stepResults.length,
                                        ")"
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                    lineNumber: 190,
                                    columnNumber: 17
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                    style: {
                                        display: "flex",
                                        flexDirection: "column",
                                        gap: "0.65rem"
                                    },
                                    children: stepResults.map((step)=>{
                                        const color = step.status === "complete" ? "#10b981" : step.status === "error" ? "#ef4444" : "#2563eb";
                                        return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            style: {
                                                borderLeft: `3px solid ${color}`,
                                                background: "#f8fafc",
                                                borderRadius: "0.5rem",
                                                padding: "0.75rem 0.9rem"
                                            },
                                            children: [
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                                    style: {
                                                        display: "flex",
                                                        justifyContent: "space-between",
                                                        gap: "0.75rem"
                                                    },
                                                    children: [
                                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                            style: {
                                                                fontWeight: 600,
                                                                fontSize: "0.82rem"
                                                            },
                                                            children: step.title
                                                        }, void 0, false, {
                                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                                            lineNumber: 199,
                                                            columnNumber: 27
                                                        }, this),
                                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                            style: {
                                                                color,
                                                                fontSize: "0.7rem",
                                                                textTransform: "capitalize"
                                                            },
                                                            children: step.status
                                                        }, void 0, false, {
                                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                                            lineNumber: 200,
                                                            columnNumber: 27
                                                        }, this)
                                                    ]
                                                }, void 0, true, {
                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                    lineNumber: 198,
                                                    columnNumber: 25
                                                }, this),
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                                    style: {
                                                        color: "#64748b",
                                                        fontSize: "0.75rem",
                                                        lineHeight: 1.5,
                                                        marginTop: "0.3rem",
                                                        whiteSpace: "pre-wrap",
                                                        maxHeight: "10rem",
                                                        overflowY: "auto"
                                                    },
                                                    children: step.detail
                                                }, void 0, false, {
                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                    lineNumber: 202,
                                                    columnNumber: 25
                                                }, this)
                                            ]
                                        }, step.key, true, {
                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                            lineNumber: 197,
                                            columnNumber: 23
                                        }, this);
                                    })
                                }, void 0, false, {
                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                    lineNumber: 193,
                                    columnNumber: 17
                                }, this)
                            ]
                        }, void 0, true, {
                            fileName: "[project]/src/components/ResultsPanel.tsx",
                            lineNumber: 181,
                            columnNumber: 15
                        }, this),
                        result && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["Fragment"], {
                            children: [
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                                    style: {
                                        background: "white",
                                        border: "1px solid #e2e8f0",
                                        borderRadius: "0.75rem",
                                        padding: "1.25rem",
                                        boxShadow: "0 1px 4px rgba(0,0,0,0.05)"
                                    },
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            style: {
                                                fontWeight: 600,
                                                marginBottom: "1rem",
                                                fontSize: "0.9rem"
                                            },
                                            children: "Summary"
                                        }, void 0, false, {
                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                            lineNumber: 223,
                                            columnNumber: 15
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            style: {
                                                display: "grid",
                                                gridTemplateColumns: "repeat(3, 1fr)",
                                                gap: "0.75rem"
                                            },
                                            children: [
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(StatCard, {
                                                    value: result.data_factors.length,
                                                    label: "Data Factors",
                                                    color: "#2563eb"
                                                }, void 0, false, {
                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                    lineNumber: 233,
                                                    columnNumber: 17
                                                }, this),
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(StatCard, {
                                                    value: result.research_signals.length,
                                                    label: "Research Signals",
                                                    color: "#10b981"
                                                }, void 0, false, {
                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                    lineNumber: 234,
                                                    columnNumber: 17
                                                }, this),
                                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(StatCard, {
                                                    value: result.best_signals.length,
                                                    label: "Best Signals",
                                                    color: "#f59e0b"
                                                }, void 0, false, {
                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                    lineNumber: 235,
                                                    columnNumber: 17
                                                }, this)
                                            ]
                                        }, void 0, true, {
                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                            lineNumber: 226,
                                            columnNumber: 15
                                        }, this)
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                    lineNumber: 214,
                                    columnNumber: 13
                                }, this),
                                result.best_signals.length > 0 && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                                    style: {
                                        background: "white",
                                        border: "1px solid #e2e8f0",
                                        borderRadius: "0.75rem",
                                        padding: "1.25rem",
                                        boxShadow: "0 1px 4px rgba(0,0,0,0.05)"
                                    },
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            style: {
                                                fontWeight: 600,
                                                marginBottom: "1rem",
                                                fontSize: "0.9rem"
                                            },
                                            children: [
                                                "Trading Signals (",
                                                result.best_signals.length,
                                                ")"
                                            ]
                                        }, void 0, true, {
                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                            lineNumber: 250,
                                            columnNumber: 17
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            style: {
                                                display: "flex",
                                                flexDirection: "column",
                                                gap: "0.55rem"
                                            },
                                            children: result.best_signals.map((signal, i)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(SignalRow, {
                                                    signal: signal
                                                }, i, false, {
                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                    lineNumber: 255,
                                                    columnNumber: 21
                                                }, this))
                                        }, void 0, false, {
                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                            lineNumber: 253,
                                            columnNumber: 17
                                        }, this)
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                    lineNumber: 241,
                                    columnNumber: 15
                                }, this),
                                result.data_factors.length > 0 && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                                    style: {
                                        background: "white",
                                        border: "1px solid #e2e8f0",
                                        borderRadius: "0.75rem",
                                        padding: "1.25rem",
                                        boxShadow: "0 1px 4px rgba(0,0,0,0.05)"
                                    },
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            style: {
                                                fontWeight: 600,
                                                marginBottom: "1rem",
                                                fontSize: "0.9rem"
                                            },
                                            children: [
                                                "Data Agent Results (",
                                                result.data_factors.length,
                                                ")"
                                            ]
                                        }, void 0, true, {
                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                            lineNumber: 272,
                                            columnNumber: 17
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            style: {
                                                display: "flex",
                                                flexDirection: "column",
                                                gap: "0.75rem"
                                            },
                                            children: result.data_factors.map((factor, i)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                                    style: {
                                                        border: "1px solid #e2e8f0",
                                                        borderRadius: "0.625rem",
                                                        padding: "0.9rem 1rem"
                                                    },
                                                    children: [
                                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                                            style: {
                                                                fontWeight: 600,
                                                                fontSize: "0.85rem",
                                                                marginBottom: "0.5rem"
                                                            },
                                                            children: [
                                                                factor.agent_name ?? `Data Agent ${i + 1}`,
                                                                factor.source_name && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                                    style: {
                                                                        color: "#64748b",
                                                                        fontWeight: 400
                                                                    },
                                                                    children: ` · ${factor.source_name}`
                                                                }, void 0, false, {
                                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                                    lineNumber: 288,
                                                                    columnNumber: 27
                                                                }, this),
                                                                factor.partial && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("span", {
                                                                    style: {
                                                                        marginLeft: "0.5rem",
                                                                        color: "#2563eb",
                                                                        fontSize: "0.72rem"
                                                                    },
                                                                    children: "Processing..."
                                                                }, void 0, false, {
                                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                                    lineNumber: 293,
                                                                    columnNumber: 27
                                                                }, this)
                                                            ]
                                                        }, void 0, true, {
                                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                                            lineNumber: 285,
                                                            columnNumber: 23
                                                        }, this),
                                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                                            style: {
                                                                color: "#475569",
                                                                fontSize: "0.78rem",
                                                                lineHeight: 1.6,
                                                                whiteSpace: "pre-wrap",
                                                                maxHeight: "16rem",
                                                                overflowY: "auto"
                                                            },
                                                            children: factor.context_string || "Completed without a text summary."
                                                        }, void 0, false, {
                                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                                            lineNumber: 298,
                                                            columnNumber: 23
                                                        }, this)
                                                    ]
                                                }, `${factor.agent_name ?? "data"}-${i}`, true, {
                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                    lineNumber: 277,
                                                    columnNumber: 21
                                                }, this))
                                        }, void 0, false, {
                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                            lineNumber: 275,
                                            columnNumber: 17
                                        }, this)
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                    lineNumber: 263,
                                    columnNumber: 15
                                }, this),
                                result.research_signals.length > 0 && /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("section", {
                                    style: {
                                        background: "white",
                                        border: "1px solid #e2e8f0",
                                        borderRadius: "0.75rem",
                                        padding: "1.25rem",
                                        boxShadow: "0 1px 4px rgba(0,0,0,0.05)"
                                    },
                                    children: [
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            style: {
                                                fontWeight: 600,
                                                marginBottom: "1rem",
                                                fontSize: "0.9rem"
                                            },
                                            children: [
                                                "Research Agent Results (",
                                                result.research_signals.length,
                                                ")"
                                            ]
                                        }, void 0, true, {
                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                            lineNumber: 324,
                                            columnNumber: 17
                                        }, this),
                                        /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                            style: {
                                                display: "flex",
                                                flexDirection: "column",
                                                gap: "0.55rem"
                                            },
                                            children: result.research_signals.map((signal, i)=>/*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(SignalRow, {
                                                    signal: signal
                                                }, `${signal.agent_id ?? "research"}-${signal.signal_index ?? i}`, false, {
                                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                                    lineNumber: 329,
                                                    columnNumber: 21
                                                }, this))
                                        }, void 0, false, {
                                            fileName: "[project]/src/components/ResultsPanel.tsx",
                                            lineNumber: 327,
                                            columnNumber: 17
                                        }, this)
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                    lineNumber: 315,
                                    columnNumber: 15
                                }, this),
                                /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                                    style: {
                                        fontSize: "0.72rem",
                                        color: "#94a3b8",
                                        textAlign: "right"
                                    },
                                    children: [
                                        "Analysis at: ",
                                        result.trigger_time
                                    ]
                                }, void 0, true, {
                                    fileName: "[project]/src/components/ResultsPanel.tsx",
                                    lineNumber: 335,
                                    columnNumber: 13
                                }, this)
                            ]
                        }, void 0, true, {
                            fileName: "[project]/src/components/ResultsPanel.tsx",
                            lineNumber: 212,
                            columnNumber: 25
                        }, this)
                    ]
                }, void 0, true, {
                    fileName: "[project]/src/components/ResultsPanel.tsx",
                    lineNumber: 179,
                    columnNumber: 11
                }, this)
            }, void 0, false, {
                fileName: "[project]/src/components/ResultsPanel.tsx",
                lineNumber: 162,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("style", {
                children: `@keyframes spin { to { transform: rotate(360deg); } }`
            }, void 0, false, {
                fileName: "[project]/src/components/ResultsPanel.tsx",
                lineNumber: 343,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/ResultsPanel.tsx",
        lineNumber: 108,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/components/TradingDashboard.tsx [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "default",
    ()=>TradingDashboard
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react-jsx-dev-runtime.js [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$Header$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/Header.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ChatPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/ChatPanel.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ResultsPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/components/ResultsPanel.tsx [app-ssr] (ecmascript)");
var __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$hooks$2f$useTrading$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/src/hooks/useTrading.ts [app-ssr] (ecmascript)");
"use client";
;
;
;
;
;
function TradingDashboard({ initialHealth }) {
    const { connected, running, messages, result, stepResults, startAnalysis } = (0, __TURBOPACK__imported__module__$5b$project$5d2f$src$2f$hooks$2f$useTrading$2e$ts__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useTrading"])();
    const agentCounts = initialHealth ? {
        data: initialHealth.agents.data_agents,
        research: initialHealth.agents.research_agents
    } : null;
    return /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
        style: {
            display: "flex",
            flexDirection: "column",
            height: "100vh",
            overflow: "hidden"
        },
        children: [
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$Header$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["default"], {
                connected: connected,
                agentCounts: agentCounts
            }, void 0, false, {
                fileName: "[project]/src/components/TradingDashboard.tsx",
                lineNumber: 35,
                columnNumber: 7
            }, this),
            /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])("div", {
                style: {
                    flex: 1,
                    display: "grid",
                    gridTemplateColumns: "44% 1fr",
                    gap: "1px",
                    background: "#e2e8f0",
                    overflow: "hidden",
                    minHeight: 0
                },
                children: [
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ChatPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["default"], {
                        messages: messages,
                        running: running,
                        onStart: startAnalysis
                    }, void 0, false, {
                        fileName: "[project]/src/components/TradingDashboard.tsx",
                        lineNumber: 48,
                        columnNumber: 9
                    }, this),
                    /*#__PURE__*/ (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2d$jsx$2d$dev$2d$runtime$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["jsxDEV"])(__TURBOPACK__imported__module__$5b$project$5d2f$src$2f$components$2f$ResultsPanel$2e$tsx__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["default"], {
                        result: result,
                        stepResults: stepResults,
                        running: running
                    }, void 0, false, {
                        fileName: "[project]/src/components/TradingDashboard.tsx",
                        lineNumber: 49,
                        columnNumber: 9
                    }, this)
                ]
            }, void 0, true, {
                fileName: "[project]/src/components/TradingDashboard.tsx",
                lineNumber: 37,
                columnNumber: 7
            }, this)
        ]
    }, void 0, true, {
        fileName: "[project]/src/components/TradingDashboard.tsx",
        lineNumber: 27,
        columnNumber: 5
    }, this);
}
}),
"[project]/src/hooks/useTrading.ts [app-ssr] (ecmascript)", ((__turbopack_context__) => {
"use strict";

__turbopack_context__.s([
    "useTrading",
    ()=>useTrading
]);
var __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__ = __turbopack_context__.i("[project]/node_modules/next/dist/server/route-modules/app-page/vendored/ssr/react.js [app-ssr] (ecmascript)");
"use client";
;
let seq = 0;
const uid = ()=>String(++seq);
/**
 * Builds a stable key for upserting agent status messages in chat.
 * @generated AI Assistant - 2026-08-07 15:40:00
 */ function buildAgentKey(agentType, agentId) {
    return `${agentType}_${String(agentId ?? "unknown")}`;
}
function useTrading() {
    const [connected, setConnected] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const [running, setRunning] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(false);
    const [messages, setMessages] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])([
        {
            id: uid(),
            role: "system",
            text: "Welcome to AI Trading System. Click Start Analysis to begin.",
            timestamp: new Date()
        }
    ]);
    const [result, setResult] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])(null);
    const [stepResults, setStepResults] = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useState"])([]);
    const esRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(null);
    const streamFinishedRef = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useRef"])(false);
    const push = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((msg)=>{
        setMessages((prev)=>[
                ...prev,
                {
                    ...msg,
                    id: uid(),
                    timestamp: new Date()
                }
            ]);
    }, []);
    const upsertStepResult = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((step)=>{
        setStepResults((previous)=>{
            const index = previous.findIndex((item)=>item.key === step.key);
            if (index < 0) return [
                ...previous,
                step
            ];
            const updated = [
                ...previous
            ];
            updated[index] = step;
            return updated;
        });
    }, []);
    /**
   * Upserts an agent message so start/complete/error update the same bubble.
   * @generated AI Assistant - 2026-08-07 15:40:00
   */ const upsertAgentMessage = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((agentKey, msg)=>{
        setMessages((prev)=>{
            const idx = prev.findIndex((m)=>m.agentKey === agentKey);
            if (idx >= 0) {
                const updated = [
                    ...prev
                ];
                updated[idx] = {
                    ...updated[idx],
                    ...msg,
                    agentKey,
                    timestamp: new Date()
                };
                return updated;
            }
            return [
                ...prev,
                {
                    ...msg,
                    id: uid(),
                    agentKey,
                    timestamp: new Date()
                }
            ];
        });
    }, []);
    /**
   * Closes SSE connection and resets running state.
   * @generated AI Assistant - 2026-08-07 15:40:00
   */ const closeStream = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])((finished)=>{
        streamFinishedRef.current = finished;
        esRef.current?.close();
        esRef.current = null;
        setRunning(false);
        setConnected(false);
    }, []);
    const startAnalysis = (0, __TURBOPACK__imported__module__$5b$project$5d2f$node_modules$2f$next$2f$dist$2f$server$2f$route$2d$modules$2f$app$2d$page$2f$vendored$2f$ssr$2f$react$2e$js__$5b$app$2d$ssr$5d$__$28$ecmascript$29$__["useCallback"])(async (triggerTime)=>{
        if (running) return;
        setRunning(true);
        setResult(null);
        setStepResults([]);
        streamFinishedRef.current = false;
        push({
            role: "user",
            text: `Start analysis at ${triggerTime || "now"}`
        });
        const res = await fetch("/api/start", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                trigger_time: triggerTime ?? ""
            })
        });
        if (!res.ok) {
            push({
                role: "system",
                text: "Failed to start analysis."
            });
            setRunning(false);
            return;
        }
        const { session_id } = await res.json();
        esRef.current?.close();
        const es = new EventSource(`/api/stream/${session_id}`);
        esRef.current = es;
        setConnected(true);
        es.onopen = ()=>{
            setConnected(true);
        };
        es.onmessage = (ev)=>{
            const event = JSON.parse(ev.data);
            const { type, data } = event;
            const timestamp = event.timestamp ?? new Date().toISOString();
            switch(type){
                case "system":
                    push({
                        role: "system",
                        text: String(data.message ?? "")
                    });
                    upsertStepResult({
                        key: `system:${String(data.stage ?? "init")}`,
                        title: "Analysis initialized",
                        detail: String(data.message ?? ""),
                        status: "running",
                        timestamp
                    });
                    break;
                case "stage":
                    push({
                        role: "system",
                        text: String(data.message ?? "")
                    });
                    upsertStepResult({
                        key: `stage:${String(data.stage ?? "unknown")}`,
                        title: String(data.message ?? "Processing"),
                        detail: data.total != null ? `${String(data.total)} agents` : "Processing...",
                        status: "running",
                        timestamp
                    });
                    break;
                case "stage_complete":
                    push({
                        role: "system",
                        text: String(data.message ?? "")
                    });
                    upsertStepResult({
                        key: `stage:${String(data.stage ?? "unknown")}`,
                        title: String(data.stage ?? "Stage").replaceAll("_", " "),
                        detail: String(data.message ?? "Completed"),
                        status: "complete",
                        timestamp
                    });
                    break;
                case "complete":
                    push({
                        role: "system",
                        text: String(data.message ?? "")
                    });
                    upsertStepResult({
                        key: "analysis:complete",
                        title: "Analysis workflow completed",
                        detail: `${String(data.data_factors_count ?? 0)} data factors · ${String(data.research_signals_count ?? 0)} research signals · ${String(data.best_signals_count ?? 0)} best signals`,
                        status: "complete",
                        timestamp
                    });
                    break;
                case "agent_start":
                    {
                        const agentType = data.agent_type;
                        const agentName = String(data.agent_name ?? "Agent");
                        const agentKey = buildAgentKey(agentType, data.agent_id);
                        upsertAgentMessage(agentKey, {
                            role: "system",
                            text: `${agentName} 开始工作`,
                            agentType,
                            agentName,
                            agentStatus: "start"
                        });
                        upsertStepResult({
                            key: `agent:${agentKey}`,
                            title: agentName,
                            detail: "Agent is working",
                            status: "running",
                            timestamp
                        });
                        break;
                    }
                case "agent_result":
                    {
                        const agentResult = data.result;
                        if (!agentResult) break;
                        upsertStepResult({
                            key: `source:${agentResult.agent_id ?? "unknown"}:${agentResult.source_name ?? "source"}`,
                            title: `${agentResult.agent_name ?? "Data Agent"} · ${agentResult.source_name ?? "Data source"}`,
                            detail: agentResult.context_string || "Content received",
                            status: "complete",
                            timestamp
                        });
                        setResult((current)=>{
                            const next = current ?? {
                                trigger_time: triggerTime || new Date().toLocaleString(),
                                data_factors: [],
                                research_signals: [],
                                best_signals: []
                            };
                            const resultKey = `${agentResult.agent_id ?? "unknown"}:${agentResult.source_name ?? "source"}`;
                            const existingIndex = next.data_factors.findIndex((factor)=>`${factor.agent_id ?? "unknown"}:${factor.source_name ?? "source"}` === resultKey);
                            const dataFactors = [
                                ...next.data_factors
                            ];
                            if (existingIndex >= 0) dataFactors[existingIndex] = agentResult;
                            else dataFactors.push(agentResult);
                            return {
                                ...next,
                                data_factors: dataFactors
                            };
                        });
                        break;
                    }
                case "agent_complete":
                    {
                        const agentType = data.agent_type;
                        const agentName = String(data.agent_name ?? "Agent");
                        const agentKey = buildAgentKey(agentType, data.agent_id);
                        upsertAgentMessage(agentKey, {
                            role: "system",
                            text: `${agentName} 已完成`,
                            agentType,
                            agentName,
                            agentStatus: "complete"
                        });
                        upsertStepResult({
                            key: `agent:${agentKey}`,
                            title: agentName,
                            detail: agentType === "research" ? `${String(data.signals_count ?? 0)} signals produced` : "Final agent result produced",
                            status: "complete",
                            timestamp
                        });
                        // Show this agent's output immediately; do not wait for the whole
                        // workflow's final `result` event.
                        setResult((current)=>{
                            const next = current ?? {
                                trigger_time: triggerTime || new Date().toLocaleString(),
                                data_factors: [],
                                research_signals: [],
                                best_signals: []
                            };
                            const agentResult = data.result;
                            if (agentType === "data" && agentResult) {
                                const completedAgentId = agentResult.agent_id;
                                return {
                                    ...next,
                                    data_factors: [
                                        ...next.data_factors.filter((factor)=>factor.agent_id !== completedAgentId),
                                        agentResult
                                    ]
                                };
                            }
                            if (agentType === "research" && agentResult) {
                                const signals = Array.isArray(agentResult.signals) ? agentResult.signals : [];
                                return {
                                    ...next,
                                    research_signals: [
                                        ...next.research_signals,
                                        ...signals
                                    ]
                                };
                            }
                            return next;
                        });
                        break;
                    }
                case "agent_error":
                    {
                        const agentType = data.agent_type;
                        const agentName = String(data.agent_name ?? "Agent");
                        const agentKey = buildAgentKey(agentType, data.agent_id);
                        upsertAgentMessage(agentKey, {
                            role: "system",
                            text: `${agentName} 执行失败：${String(data.message ?? "")}`,
                            agentType,
                            agentName,
                            agentStatus: "error"
                        });
                        upsertStepResult({
                            key: `agent:${agentKey}`,
                            title: agentName,
                            detail: String(data.message ?? "Agent failed"),
                            status: "error",
                            timestamp
                        });
                        break;
                    }
                case "result":
                    {
                        const finalResult = data.result;
                        upsertStepResult({
                            key: "result:final",
                            title: "Final result",
                            detail: `${finalResult.data_factors.length} data factors · ${finalResult.research_signals.length} research signals · ${finalResult.best_signals.length} best signals`,
                            status: "complete",
                            timestamp
                        });
                        setResult(finalResult);
                        push({
                            role: "system",
                            text: "分析完成，结果已更新。"
                        });
                        closeStream(true);
                        break;
                    }
                case "stream_end":
                    closeStream(true);
                    break;
                case "error":
                    push({
                        role: "system",
                        text: String(data.message ?? "Error occurred")
                    });
                    closeStream(true);
                    break;
            }
        };
        es.onerror = ()=>{
            if (streamFinishedRef.current) {
                esRef.current = null;
                return;
            }
            // EventSource reconnects automatically. Keep the analysis running and
            // retain the session instead of turning a temporary proxy reset into
            // a permanent failure.
            setConnected(false);
        };
    }, [
        running,
        push,
        upsertAgentMessage,
        upsertStepResult,
        closeStream
    ]);
    return {
        connected,
        running,
        messages,
        result,
        stepResults,
        startAnalysis
    };
}
}),
];

//# sourceMappingURL=_1qrkgdl._.js.map
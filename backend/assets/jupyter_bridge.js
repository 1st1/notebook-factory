(function () {
        var parsedUrl = new URL(window.location.href);
        if (parsedUrl.searchParams.get("token")) {
          parsedUrl.searchParams.delete("token");
          window.history.replaceState({}, "", parsedUrl.href);
        }

        var bridgeToken = window.location.pathname.split("/").filter(Boolean)[0];
        var jupyterApp;
        var focusedShell;
        var applyingFocusedLayout = false;
        var focusedLayoutTimeout;
        var fitFrame;
        var fitTimeouts = [];

        function fitJupyterLayout() {
          if (!jupyterApp || !jupyterApp.shell) return;
          jupyterApp.shell.fit();
          jupyterApp.shell.update();
        }

        function scheduleJupyterFit() {
          window.cancelAnimationFrame(fitFrame);
          fitTimeouts.forEach(function (timeout) {
            window.clearTimeout(timeout);
          });
          fitTimeouts = [];
          fitFrame = window.requestAnimationFrame(function () {
            fitFrame = window.requestAnimationFrame(fitJupyterLayout);
          });
          [100, 250, 500].forEach(function (delay) {
            fitTimeouts.push(window.setTimeout(fitJupyterLayout, delay));
          });
        }

        function scheduleFocusedLayout() {
          window.clearTimeout(focusedLayoutTimeout);
          focusedLayoutTimeout = window.setTimeout(configureFocusedLayout, 0);
        }

        function handleLayoutModified() {
          if (!applyingFocusedLayout) scheduleFocusedLayout();
        }

        function configureFocusedLayout() {
          var app = window.jupyterapp;
          if (!app || !app.shell) return false;

          var shell = app.shell;
          if (focusedShell !== shell) {
            if (focusedShell) {
              focusedShell.layoutModified.disconnect(handleLayoutModified);
            }
            shell.layoutModified.connect(handleLayoutModified);
            focusedShell = shell;
          }

          applyingFocusedLayout = true;
          try {
            if (!shell.leftCollapsed) shell.collapseLeft();
            if (!shell.rightCollapsed) shell.collapseRight();
            if (
              typeof shell.collapseDown === "function" &&
              !shell.downCollapsed
            ) {
              shell.collapseDown();
            }
            if (shell.isSideTabBarVisible("left")) {
              shell.toggleSideTabBarVisibility("left");
            }
            if (shell.isSideTabBarVisible("right")) {
              shell.toggleSideTabBarVisibility("right");
            }
            if (
              shell.mode === "single-document" &&
              shell.isTopInSimpleModeVisible()
            ) {
              shell.toggleTopInSimpleModeVisibility();
            }
            var menuWidget = Array.from(shell.widgets("menu"))[0];
            var menuPanel = menuWidget && menuWidget.parent;
            if (
              menuPanel &&
              menuPanel.id === "jp-menu-panel" &&
              !menuPanel.isHidden
            ) {
              menuPanel.hide();
            }
          } finally {
            applyingFocusedLayout = false;
          }

          shell.node.dataset.vercelFocusedEditor = "true";
          jupyterApp = app;
          scheduleJupyterFit();
          return true;
        }

        function waitForJupyterApp() {
          var app = window.jupyterapp;
          if (!app) {
            window.setTimeout(waitForJupyterApp, 50);
            return;
          }
          Promise.resolve(app.restored).catch(function () {}).then(function () {
            if (!configureFocusedLayout()) {
              window.setTimeout(waitForJupyterApp, 50);
              return;
            }
            [50, 100, 250, 500, 1000, 2000].forEach(function (delay) {
              window.setTimeout(configureFocusedLayout, delay);
            });
          });
        }

        window.addEventListener("resize", scheduleJupyterFit);
        if (window.visualViewport) {
          window.visualViewport.addEventListener("resize", scheduleJupyterFit);
        }
        new ResizeObserver(scheduleJupyterFit).observe(document.documentElement);
        waitForJupyterApp();

        window.addEventListener("message", async function (event) {
          var data = event.data;
          if (
            event.source !== window.parent ||
            event.origin !== __PARENT_ORIGIN__ ||
            !data ||
            data.type !== "vercel-notebook-save" ||
            data.token !== bridgeToken ||
            typeof data.id !== "string"
          ) return;

          try {
            var app = window.jupyterapp;
            await app.restored;
            var widget = app.shell.currentWidget;
            if (!widget || !widget.context || widget.context.path !== "notebook.ipynb") {
              throw new Error("Select notebook.ipynb before saving.");
            }
            await widget.context.save();
            event.source.postMessage({ type: "vercel-notebook-saved", id: data.id }, event.origin);
          } catch (error) {
            event.source.postMessage({
              type: "vercel-notebook-save-error",
              id: data.id,
              message: error instanceof Error ? error.message : "Jupyter could not save the notebook."
            }, event.origin);
          }
        });
      })();

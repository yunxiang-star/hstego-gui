/* 图像隐写工具 · 前端交互
 *
 * 设计目标：把 FastAPI 的接口包装成「选图 → 写内容 → 设口令 → 一键完成」四步，
 * 全程中文提示，不向用户暴露任何 JSON / 字段名。
 * 技术细节（重试流水、PSNR、sha256）折叠在「技术细节」里，默认收起。
 */
(function () {
  "use strict";

  var API = "/api/v1";

  // ------------------------------------------------------------------ 工具

  function $(id) { return document.getElementById(id); }

  function formatBytes(n) {
    if (n === null || n === undefined) { return "—"; }
    if (n < 1024) { return n + " 字节"; }
    if (n < 1024 * 1024) { return (n / 1024).toFixed(1) + " KB"; }
    return (n / 1024 / 1024).toFixed(2) + " MB";
  }

  function formatSeconds(s) {
    if (s === null || s === undefined) { return "—"; }
    return (Math.round(s * 10) / 10).toFixed(1) + " 秒";
  }

  function escapeHtml(text) {
    return String(text === null || text === undefined ? "" : text)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  var STAGE_TEXT = {
    queued: "排队中…",
    prepare: "正在检查文件",
    capacity: "正在计算这张图能藏多少内容",
    embed: "正在把内容写进图片",
    verify: "正在验证：把内容取回来核对",
    metrics: "正在生成对比预览",
    extract: "正在读取图片并解密",
    done: "完成",
    failed: "没能完成"
  };

  // 错误码 → 小白能看懂的解释
  var ERROR_TEXT = {
    not_found: {
      title: "没取出内容来",
      body: "这张图里没有读出可用的内容。下面三种情况表现完全一样，工具无法区分是哪一种：",
      list: [
        "口令输错了（大小写、空格都算数）",
        "这张图里确实没有藏过内容",
        "内容藏进去时就没能稳妥写入（JPG 图片存在约 25% 的这种情况）"
      ],
      advice: "先检查口令；如果确认无误，试着换回当初生成的那张原图——被聊天软件转发、压缩过的图片，隐藏内容会失效。"
    },
    payload_too_large: {
      title: "这张图装不下这么多内容",
      body: "载体图片能藏的量是由图片本身决定的，和文件大小无关。",
      advice: "换一张更大、纹理更丰富的图片（风景、草地、砂石这类细节多的图容量更大），或者把要藏的内容缩短、压缩后再试。"
    },
    unsupported_image: {
      title: "这个图片格式暂时不支持",
      body: "目前支持 PNG、JPG、TIFF、PGM 等常见格式。",
      advice: "用画图或看图软件把图片另存为 PNG 或 JPG 后再试。"
    },
    image_too_large: {
      title: "文件太大了",
      body: "单个文件有体积上限（默认 64 MB）。",
      advice: "压缩图片尺寸后重试。"
    },
    invalid_image: {
      title: "这个文件打不开",
      body: "它可能不是图片，或者文件已经损坏。",
      advice: "换一个文件再试。"
    },
    missing_parameter: {
      title: "还有必填项没填",
      body: "请检查图片、内容和口令是否都填写完整。",
      advice: ""
    },
    engine_unavailable: {
      title: "隐写引擎不可用",
      body: "后端的原生扩展没有加载成功，无法执行嵌入或提取。",
      advice: "请重新启动服务；若持续出现，检查工程内的两个原生扩展是否编译正确。"
    },
    verification_failed: {
      title: "试了多次，都没能稳妥地藏进去",
      body: "工具每次藏完都会立刻把内容取回来核对一遍，只有核对通过才会把图给你。这一次所有尝试都没通过，所以没有输出结果——这是保护，不是失败。",
      advice: "换一张纹理更丰富的载体图，或改用 PNG 格式的图片（PNG 走空间域，实测几乎不会失败）。"
    },
    internal_error: {
      title: "出了点意外",
      body: "后端处理时发生了未预期的错误。",
      advice: "换一个文件重试；若持续复现，请把这次的载体与内容留存下来作为案例。"
    },
    job_not_found: {
      title: "任务已过期",
      body: "服务可能重启过，任务记录已经不在了。",
      advice: "重新提交一次即可。"
    }
  };

  function errorInfo(code, message) {
    var known = ERROR_TEXT[code];
    if (known) { return known; }
    return {
      title: "没能完成",
      body: message || "发生了未预期的错误。",
      advice: ""
    };
  }

  // ------------------------------------------------------------------ 服务状态

  function checkHealth() {
    var badge = $("engineBadge");
    fetch(API + "/health")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.engine_available) {
          badge.className = "badge badge-ok";
          badge.textContent = "引擎就绪";
        } else {
          badge.className = "badge badge-err";
          badge.textContent = "引擎未就绪";
          var alert = $("engineAlert");
          $("engineAlertText").textContent =
            data.engine_import_error || "原生扩展未加载。";
          alert.hidden = false;
        }
      })
      .catch(function () {
        badge.className = "badge badge-err";
        badge.textContent = "无法连接服务";
      });
  }

  // ------------------------------------------------------------------ 标签切换

  function initTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
    tabs.forEach(function (tab) {
      tab.addEventListener("click", function () {
        tabs.forEach(function (t) { t.classList.toggle("is-active", t === tab); });
        $("panel-embed").hidden = tab.dataset.tab !== "embed";
        $("panel-extract").hidden = tab.dataset.tab !== "extract";
        window.scrollTo({ top: 0, behavior: "smooth" });
      });
    });
  }

  // ------------------------------------------------------------------ 文件选择（拖放）

  function filePicker(opts) {
    var drop = opts.drop, input = opts.input;
    var preview = opts.preview, nameEl = opts.nameEl, metaEl = opts.metaEl;
    var resetBtn = opts.resetBtn;
    var emptyBox = drop.querySelector(".drop-empty");
    var filledBox = drop.querySelector(".drop-filled");
    var state = { file: null };

    function apply(file) {
      if (!file) { return; }
      state.file = file;
      emptyBox.hidden = true;
      filledBox.hidden = false;
      nameEl.textContent = file.name;
      metaEl.textContent = formatBytes(file.size);
      if (preview) {
        if (preview.dataset.url) { URL.revokeObjectURL(preview.dataset.url); }
        var url = URL.createObjectURL(file);
        preview.dataset.url = url;
        preview.src = url;
      }
      if (opts.onChange) { opts.onChange(file); }
    }

    function reset(event) {
      if (event) { event.stopPropagation(); event.preventDefault(); }
      state.file = null;
      input.value = "";
      emptyBox.hidden = false;
      filledBox.hidden = true;
      if (preview && preview.dataset.url) {
        URL.revokeObjectURL(preview.dataset.url);
        delete preview.dataset.url;
      }
      if (opts.onChange) { opts.onChange(null); }
    }

    drop.addEventListener("click", function (event) {
      if (event.target.closest(".linkbtn")) { return; }
      input.click();
    });
    drop.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        input.click();
      }
    });
    input.addEventListener("change", function () {
      if (input.files && input.files[0]) { apply(input.files[0]); }
    });
    ["dragenter", "dragover"].forEach(function (type) {
      drop.addEventListener(type, function (event) {
        event.preventDefault();
        drop.classList.add("is-drag");
      });
    });
    ["dragleave", "drop"].forEach(function (type) {
      drop.addEventListener(type, function (event) {
        event.preventDefault();
        drop.classList.remove("is-drag");
      });
    });
    drop.addEventListener("drop", function (event) {
      var dt = event.dataTransfer;
      if (dt && dt.files && dt.files[0]) { apply(dt.files[0]); }
    });
    resetBtn.addEventListener("click", reset);

    return {
      get file() { return state.file; },
      reset: reset
    };
  }

  // ------------------------------------------------------------------ 通用：提交作业 + 跟进进度

  function friendlyStage(snapshot) {
    var message = snapshot.message || "";
    var attemptMatch = /第\s*(\d+)\s*次/.exec(message);

    if (snapshot.stage === "verify" && message.indexOf("未通过") >= 0) {
      return "第一次没藏成功，正在自动换参数重试";
    }
    if (snapshot.stage === "embed" && attemptMatch && Number(attemptMatch[1]) > 1) {
      return "正在把内容写进图片（第 " + attemptMatch[1] + " 次尝试）";
    }
    return STAGE_TEXT[snapshot.stage] || "正在处理…";
  }

  function runJob(opts) {
    var ui = opts.ui;
    var startedAt = Date.now();
    var timer = null;
    var logTimer = null;
    var source = null;
    var settled = false;

    function tick() {
      ui.elapsed.textContent = Math.round((Date.now() - startedAt) / 1000) + " 秒";
    }

    function show() {
      ui.card.hidden = false;
      ui.logs.innerHTML = "";
      tick();
      timer = setInterval(tick, 500);
    }

    function renderLogs(list) {
      ui.logs.innerHTML = "";
      (list || []).forEach(function (entry) {
        var li = el("li", null, entry.message || "");
        if (entry.level === "error") { li.style.color = "#b3261e"; }
        else if (entry.level === "warn") { li.style.color = "#8a5a00"; }
        ui.logs.appendChild(li);
      });
      if (!ui.logs.childNodes.length) {
        ui.logs.appendChild(el("li", null, "（暂无记录）"));
      }
    }

    function applySnapshot(snapshot, final) {
      ui.stage.textContent = friendlyStage(snapshot);
      var pct = Math.max(2, Math.min(100, Math.round((snapshot.progress || 0) * 100)));
      ui.bar.style.width = pct + "%";
      if (snapshot.stage === "capacity") {
        ui.sub.textContent = "正在读取图片的像素分布，图片越大这一步越久。";
      } else if (snapshot.stage === "embed" || snapshot.stage === "verify") {
        ui.sub.textContent = "单次处理大约需要 10–30 秒，请勿关闭页面。";
      } else {
        ui.sub.textContent = "请稍候…";
      }
      if (final && snapshot.logs) { renderLogs(snapshot.logs); }
    }

    function finish(status, snapshot) {
      if (settled) { return; }
      settled = true;
      clearInterval(timer);
      clearInterval(logTimer);
      if (source) { source.close(); }
      ui.card.hidden = true;
      if (opts.onDone) { opts.onDone(status, snapshot); }
    }

    show();
    ui.bar.style.width = "4%";
    ui.stage.textContent = "正在提交任务…";

    fetch(opts.url, { method: "POST", body: opts.body })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, status: response.status, data: data };
        });
      })
      .then(function (res) {
        if (!res.ok) {
          finish("failed", { error: res.data || { code: "internal_error" } });
          return;
        }
        var jobId = res.data.job_id;

        logTimer = setInterval(function () {
          fetch(API + "/jobs/" + jobId)
            .then(function (r) { return r.json(); })
            .then(function (snap) { if (snap.logs) { renderLogs(snap.logs); } })
            .catch(function () {});
        }, 2000);

        try {
          source = new EventSource(API + "/jobs/" + jobId + "/events");
        } catch (err) {
          source = null;
        }

        if (source) {
          source.addEventListener("progress", function (event) {
            applySnapshot(JSON.parse(event.data), false);
          });
          source.addEventListener("done", function (event) {
            var snapshot = JSON.parse(event.data);
            applySnapshot(snapshot, true);
            finish(snapshot.status, snapshot);
          });
          source.addEventListener("error", function () {
            // SSE 断了就退化为轮询，别让用户干等
            if (source && source.readyState === EventSource.CLOSED) {
              if (source) { source.close(); }
              pollJob(jobId, finish, applySnapshot);
            }
          });
        } else {
          pollJob(jobId, finish, applySnapshot);
        }
      })
      .catch(function () {
        finish("failed", { error: { code: "internal_error", message: "无法连接后端服务。" } });
      });
  }

  function pollJob(jobId, finish, applySnapshot) {
    var timer = setInterval(function () {
      fetch(API + "/jobs/" + jobId)
        .then(function (r) { return r.json(); })
        .then(function (snapshot) {
          applySnapshot(snapshot, true);
          if (snapshot.status === "succeeded" || snapshot.status === "failed") {
            clearInterval(timer);
            finish(snapshot.status, snapshot);
          }
        })
        .catch(function () {});
    }, 1500);
  }

  // ------------------------------------------------------------------ 结果：公共片段

  function detailPanel(rows, journal) {
    var wrap = el("details", "details");
    wrap.appendChild(el("summary", null, "技术细节（答辩/复核时用）"));
    var table = el("table", "tech");
    rows.forEach(function (row) {
      var tr = el("tr");
      tr.appendChild(el("th", null, row[0]));
      var td = el("td");
      if (row[2] === "mono") { td.className = "mono"; }
      td.textContent = row[1];
      tr.appendChild(td);
      table.appendChild(tr);
    });
    wrap.appendChild(table);

    if (journal && journal.length) {
      var t2 = el("table", "tech");
      var head = el("tr");
      ["次数", "参数", "容量", "自检", "结果", "耗时"].forEach(function (h) {
        head.appendChild(el("th", null, h));
      });
      t2.appendChild(head);
      journal.forEach(function (item) {
        var tr = el("tr");
        tr.appendChild(el("td", null, "#" + (item.index + 1)));
        tr.appendChild(el("td", null, item.quality === null || item.quality === undefined
          ? "原始载体" : "重编码 q" + item.quality));
        tr.appendChild(el("td", null, formatBytes(item.capacity_bytes)));
        tr.appendChild(el("td", null, item.verified ? "通过" : "未通过"));
        tr.appendChild(el("td", null, item.verified ? "采用" : (item.failure_reason || "失败")));
        var td = el("td", "num", formatSeconds(item.elapsed_seconds));
        tr.appendChild(td);
        t2.appendChild(tr);
      });
      wrap.appendChild(t2);
    }
    return wrap;
  }

  function downloadButton(url, filename, label) {
    var a = el("a", "btn btn-primary", label || "下载");
    a.href = url;
    if (filename) { a.setAttribute("download", filename); }
    return a;
  }

  function shot(src, title, caption) {
    var fig = el("figure", "shot");
    var img = el("img");
    img.src = src;
    img.alt = title;
    img.loading = "lazy";
    fig.appendChild(img);
    var cap = el("figcaption");
    cap.appendChild(el("strong", null, title));
    if (caption) { cap.appendChild(document.createTextNode(caption)); }
    fig.appendChild(cap);
    return fig;
  }

  function metricsSentence(metrics) {
    if (!metrics) { return ""; }
    var parts = [];
    if (metrics.max_abs_diff !== undefined && metrics.max_abs_diff !== null) {
      parts.push("单个像素最多只改动了 " + metrics.max_abs_diff + " 个灰度级");
    }
    if (metrics.changed_samples !== undefined && metrics.changed_samples !== null) {
      var ratio = metrics.changed_ratio;
      parts.push("一共 " + metrics.changed_samples + " 个像素被改动（占 " +
        (ratio !== undefined && ratio !== null
          ? (ratio * 100).toFixed(3) + "%" : "极少") + "）");
    }
    if (metrics.psnr_db) {
      parts.push("画质 " + Number(metrics.psnr_db).toFixed(1) +
        " dB（超过 40 dB 就已看不出差别）");
    }
    return parts.join("，");
  }

  // ------------------------------------------------------------------ 面板 1：藏

  function initEmbed() {
    var payloadMode = "text";
    var coverFile = null;
    var payloadFile = null;
    var capToken = 0;
    var capTimer = null;

    var picker = filePicker({
      drop: $("coverDrop"), input: $("coverInput"),
      preview: $("coverPreview"), nameEl: $("coverName"), metaEl: $("coverMeta"),
      resetBtn: $("coverReset"),
      onChange: function (file) {
        coverFile = file;
        scheduleCapacity();
        refreshButton();
      }
    });

    // ---- 内容类型切换
    var segItems = Array.prototype.slice.call(document.querySelectorAll("#payloadMode .seg-item"));
    segItems.forEach(function (item) {
      item.addEventListener("click", function () {
        payloadMode = item.dataset.mode;
        segItems.forEach(function (i) { i.classList.toggle("is-active", i === item); });
        $("payloadTextWrap").hidden = payloadMode !== "text";
        $("payloadFileWrap").hidden = payloadMode !== "file";
        scheduleCapacity();
        refreshButton();
      });
    });

    $("payloadText").addEventListener("input", function () {
      $("payloadTextSize").textContent = new Blob([$("payloadText").value]).size;
      scheduleCapacity();
      refreshButton();
    });

    $("payloadFile").addEventListener("change", function (event) {
      payloadFile = event.target.files && event.target.files[0] ? event.target.files[0] : null;
      $("payloadFileLabel").textContent = payloadFile
        ? payloadFile.name + "（" + formatBytes(payloadFile.size) + "）"
        : "点击选择要藏的文件";
      scheduleCapacity();
      refreshButton();
    });

    $("password").addEventListener("input", refreshButton);

    $("togglePwd").addEventListener("click", function () {
      var input = $("password");
      var shown = input.type === "text";
      input.type = shown ? "password" : "text";
      $("togglePwd").textContent = shown ? "显示" : "隐藏";
    });

    // ---- 按钮可用性
    function hasPayload() {
      if (payloadMode === "text") { return $("payloadText").value.trim().length > 0; }
      return !!payloadFile;
    }

    function refreshButton() {
      var ready = !!coverFile && hasPayload() && $("password").value.length > 0;
      $("embedBtn").disabled = !ready;
      if (ready) {
        $("embedReadyNote").textContent = "一切就绪。口令请记牢，忘了就取不回来了。";
      } else if (!coverFile) {
        $("embedReadyNote").textContent = "请先选好载体图片和要藏的内容";
      } else if (!hasPayload()) {
        $("embedReadyNote").textContent = "还差「要藏的内容」没填";
      } else {
        $("embedReadyNote").textContent = "还差口令没设置";
      }
      return ready;
    }

    // ---- 容量预估（自动，防抖）
    function scheduleCapacity() {
      if (capTimer) { clearTimeout(capTimer); }
      if (!coverFile || !hasPayload()) {
        $("capacityBox").hidden = true;
        return;
      }
      capTimer = setTimeout(estimate, 600);
    }

    function estimate() {
      var box = $("capacityBox");
      var myToken = ++capToken;
      box.hidden = false;
      box.className = "capacity";
      $("capMax").textContent = "正在估算…";
      $("capNeed").textContent = "正在估算…";
      $("capNote").textContent = "正在读取图片的像素分布，通常几秒内完成。";
      $("capGauge").style.width = "0%";

      var form = new FormData();
      form.append("cover", coverFile);
      if (payloadMode === "text") {
        form.append("payload_text", $("payloadText").value);
      } else {
        form.append("payload_file", payloadFile);
      }

      fetch(API + "/capacity", { method: "POST", body: form })
        .then(function (r) {
          return r.json().then(function (data) {
            return { ok: r.ok, data: data };
          });
        })
        .then(function (res) {
          if (myToken !== capToken) { return; }
          if (!res.ok) {
            box.hidden = true;
            return;
          }
          var data = res.data;
          var maxBytes = data.capacity_bytes - data.cipher_overhead_bytes;
          var need = data.payload_cipher_bytes;
          var ratio = maxBytes > 0 ? need / maxBytes : 1;

          $("capMax").textContent = "≈ " + formatBytes(maxBytes);
          $("capNeed").textContent = "≈ " + formatBytes(need) + "（加密后）";
          $("capGauge").style.width = Math.min(100, Math.round(ratio * 100)) + "%";

          if (data.fits) {
            box.classList.add("is-ok");
            $("capNote").textContent =
              "✓ 装得下，大约用掉了这张图 " + Math.round(ratio * 100) + "% 的容量。";
          } else {
            box.classList.add("is-bad");
            $("capNote").textContent =
              "✗ 装不下。这张图最多只能藏 " + formatBytes(maxBytes) +
              "，你的内容加密后需要 " + formatBytes(need) +
              "。请换一张更大、细节更多的图，或缩短内容。";
          }
        })
        .catch(function () {
          if (myToken === capToken) { box.hidden = true; }
        });
    }

    // ---- 提交
    $("embedBtn").addEventListener("click", function () {
      if (!refreshButton()) { return; }

      var form = new FormData();
      form.append("cover", coverFile);
      form.append("password", $("password").value);
      if (payloadMode === "text") {
        form.append("payload_text", $("payloadText").value);
      } else {
        form.append("payload_file", payloadFile);
      }
      form.append("engine_name", "hstego");
      form.append("include_diff", "true");
      form.append("diff_gain", "20");
      form.append("precheck", "true");

      $("embedResult").innerHTML = "";
      $("embedBtn").disabled = true;

      runJob({
        url: API + "/embed",
        body: form,
        ui: {
          card: $("embedProgress"),
          stage: $("embedStage"),
          bar: $("embedBar"),
          sub: $("embedSub"),
          elapsed: $("embedElapsed"),
          logs: $("embedLogs")
        },
        onDone: function (status, snapshot) {
          refreshButton();
          if (status === "succeeded") {
            renderEmbedSuccess(snapshot);
          } else {
            renderEmbedFailure(snapshot);
          }
        }
      });
    });

    function renderEmbedSuccess(snapshot) {
      var report = snapshot.result || {};
      var box = $("embedResult");
      box.innerHTML = "";

      var card = el("div", "card");

      var head = el("div", "result-head");
      head.appendChild(el("div", "result-icon ok", "✓"));
      var headText = el("div");
      headText.appendChild(el("h2", "result-title", "藏好了，而且刚刚验证通过"));
      headText.appendChild(el("p", "result-sub",
        "内容已写入图片，并且立刻被取回来核对过一遍——确认能被完整取出。"));
      head.appendChild(headText);
      card.appendChild(head);

      var line = el("p", "result-line");
      line.appendChild(el("strong", null, "藏了什么："));
      line.appendChild(document.createTextNode(
        report.payload_bytes + " 字节的内容" +
        (report.is_text && report.text_preview
          ? "（文字：" + report.text_preview.slice(0, 40).replace(/\n/g, " ") +
            (report.text_preview.length > 40 ? "…" : "") + "）"
          : "")
      ));
      card.appendChild(line);

      // 图片对照
      var artifacts = report.artifacts || [];
      function find(kind) {
        for (var i = 0; i < artifacts.length; i++) {
          if (artifacts[i].kind === kind) { return artifacts[i]; }
        }
        return null;
      }
      var stegoArt = find("stego");
      var coverArt = find("cover");
      var diffArt = find("diff");

      var shots = el("div", "shots");
      if (coverArt) {
        shots.appendChild(shot(coverArt.preview_url, "藏之前", "你上传的这张原图"));
      }
      if (stegoArt) {
        shots.appendChild(shot(stegoArt.preview_url, "藏之后", "画面上看不出区别，下载这张去用"));
      }
      if (shots.childNodes.length) { card.appendChild(shots); }

      var quality = metricsSentence(report.metrics_vs_original || report.metrics);
      if (quality) {
        var q = el("p", "result-line");
        q.appendChild(el("strong", null, "改动有多大："));
        q.appendChild(document.createTextNode(quality + "——所以肉眼绝对看不出来。"));
        card.appendChild(q);
      }

      // 重试说明
      if (report.retry_used) {
        var journal = report.attempt_journal || [];
        var okIndex = 0;
        journal.forEach(function (item) { if (item.verified) { okIndex = item.index + 1; } });
        card.appendChild(el("p", "notice notice-info",
          "小提示：第一次没有藏成功（JPG 图片约 25% 的概率会遇到，属于上游算法的已知缺陷），" +
          "工具自动换了参数重试，第 " + okIndex + " 次成功了。整个过程记录在下面的技术细节里。"));
      }

      var actions = el("div", "actions");
      if (stegoArt) {
        actions.appendChild(downloadButton(stegoArt.url, stegoArt.filename,
          "⬇  下载藏好后的图片"));
      }
      if (diffArt) {
        var a2 = el("a", "btn btn-ghost", "下载改动对比图");
        a2.href = diffArt.url;
        a2.setAttribute("download", diffArt.filename);
        actions.appendChild(a2);
      }
      card.appendChild(actions);

      if (diffArt) {
        card.appendChild(el("p", "notice notice-info",
          "改动对比图是一张几乎全黑的图，零星白点就是被改动的像素。它看起来「什么都没有」正是好消息" +
          "——说明改动极少；需要向别人证明改动位置时，可以用这张图。"));
      }

      var cap = report.capacity || {};
      card.appendChild(detailPanel([
        ["算法", (report.algorithm || "—") + "（" +
          (report.domain === "jpeg" ? "压缩域，JPG 图" : "空间域，PNG 类图") + "）"],
        ["载体容量（密文预算）", formatBytes(cap.capacity_bytes)],
        ["本次占用", formatBytes(cap.payload_cipher_bytes)],
        ["图片尺寸", cap.width && cap.height ? cap.width + " × " + cap.height : "—"],
        ["实际耗时", formatSeconds(report.elapsed_seconds)],
        ["载密图 SHA-256", (report.stego_sha256 || "—"), "mono"]
      ], report.attempt_journal));

      box.appendChild(card);
      card.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function renderEmbedFailure(snapshot) {
      var error = (snapshot && snapshot.error) || {};
      var info = errorInfo(error.code, error.message);
      var box = $("embedResult");
      box.innerHTML = "";

      var card = el("div", "card");
      var head = el("div", "result-head");
      head.appendChild(el("div", "result-icon bad", "!"));
      var headText = el("div");
      headText.appendChild(el("h2", "result-title", info.title));
      headText.appendChild(el("p", "result-sub", info.body));
      head.appendChild(headText);
      card.appendChild(head);

      var detail = error.detail || {};
      if (error.code === "payload_too_large" &&
          detail.capacity_bytes !== undefined) {
        card.appendChild(el("p", "result-line",
          "这张图能装 " + formatBytes(detail.capacity_bytes) +
          "，你的内容加密后需要 " + formatBytes(detail.payload_cipher_bytes) + "。"));
      }

      if (info.advice) {
        card.appendChild(el("p", "notice notice-warn", "怎么办：" + info.advice));
      }

      var hint = detail.hint;
      if (hint) {
        card.appendChild(el("p", "notice notice-info", hint));
      }

      var report = detail.report;
      var journal = report && (report.attempt_journal || report.attempts);
      if (report && journal) {
        card.appendChild(detailPanel([
          ["算法", report.algorithm || "—"],
          ["载体容量", formatBytes((report.capacity || {}).capacity_bytes)],
          ["内容加密后需要", formatBytes((report.capacity || {}).payload_cipher_bytes || report.payload_bytes)]
        ], journal));
      }

      box.appendChild(card);
      card.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  // ------------------------------------------------------------------ 面板 2：取

  function initExtract() {
    var stegoFile = null;

    filePicker({
      drop: $("stegoDrop"), input: $("stegoInput"),
      preview: $("stegoPreview"), nameEl: $("stegoName"), metaEl: $("stegoMeta"),
      resetBtn: $("stegoReset"),
      onChange: function (file) {
        stegoFile = file;
        refreshButton();
      }
    });

    $("password2").addEventListener("input", refreshButton);

    $("togglePwd2").addEventListener("click", function () {
      var input = $("password2");
      var shown = input.type === "text";
      input.type = shown ? "password" : "text";
      $("togglePwd2").textContent = shown ? "显示" : "隐藏";
    });

    function refreshButton() {
      var ready = !!stegoFile && $("password2").value.length > 0;
      $("extractBtn").disabled = !ready;
      if (ready) {
        $("extractReadyNote").textContent = "一切就绪，开始读取。";
      } else if (!stegoFile) {
        $("extractReadyNote").textContent = "请先选好图片并输入口令";
      } else {
        $("extractReadyNote").textContent = "还差口令没输入";
      }
      return ready;
    }

    $("extractBtn").addEventListener("click", function () {
      if (!refreshButton()) { return; }

      var form = new FormData();
      form.append("stego", stegoFile);
      form.append("password", $("password2").value);
      form.append("engine_name", "hstego");
      form.append("text_preview_chars", "200000");

      $("extractResult").innerHTML = "";
      $("extractBtn").disabled = true;

      runJob({
        url: API + "/extract",
        body: form,
        ui: {
          card: $("extractProgress"),
          stage: $("extractStage"),
          bar: $("extractBar"),
          sub: $("extractProgress").querySelector(".progress-sub"),
          elapsed: $("extractElapsed"),
          logs: document.createElement("ol")
        },
        onDone: function (status, snapshot) {
          refreshButton();
          if (status === "succeeded") {
            renderExtractSuccess(snapshot);
          } else {
            renderExtractFailure(snapshot);
          }
        }
      });
    });

    function renderExtractSuccess(snapshot) {
      var report = snapshot.result || {};
      var box = $("extractResult");
      box.innerHTML = "";

      var card = el("div", "card");
      var head = el("div", "result-head");
      head.appendChild(el("div", "result-icon ok", "✓"));
      var headText = el("div");
      headText.appendChild(el("h2", "result-title", "取出来了"));
      headText.appendChild(el("p", "result-sub",
        "共 " + report.payload_bytes + " 字节，耗时 " + formatSeconds(report.elapsed_seconds) + "。"));
      head.appendChild(headText);
      card.appendChild(head);

      var artifacts = report.artifacts || [];
      var extracted = null;
      artifacts.forEach(function (a) { if (a.kind === "extracted") { extracted = a; } });

      if (report.is_text && report.text) {
        var out = el("div", "textout");
        out.textContent = report.text;
        card.appendChild(out);
        if (report.text_truncated) {
          card.appendChild(el("p", "notice notice-warn",
            "内容较长，这里只显示了开头部分，完整内容请用下面的按钮下载。"));
        }
      }

      var actions = el("div", "actions");
      if (report.is_text && report.text) {
        var copyBtn = el("button", "btn btn-ghost", "复制内容");
        copyBtn.type = "button";
        copyBtn.addEventListener("click", function () {
          navigator.clipboard.writeText(report.text || "").then(function () {
            copyBtn.textContent = "已复制 ✓";
            setTimeout(function () { copyBtn.textContent = "复制内容"; }, 1500);
          }).catch(function () {
            copyBtn.textContent = "复制失败，请手动选中";
            setTimeout(function () { copyBtn.textContent = "复制内容"; }, 2000);
          });
        });
        actions.appendChild(copyBtn);
      }
      if (extracted) {
        actions.appendChild(downloadButton(extracted.url, extracted.filename,
          report.is_text ? "⬇  下载为文本文件" : "⬇  下载取出的文件"));
      }
      card.appendChild(actions);

      card.appendChild(el("p", "notice notice-info",
        "注意：提取出来的内容不包含原始文件名（隐藏时只存了内容本身），所以下载文件名是固定的 extracted.txt / extracted.bin。"));

      card.appendChild(detailPanel([
        ["算法", (report.algorithm || "—") + "（" +
          (report.domain === "jpeg" ? "压缩域" : "空间域") + "）"],
        ["内容大小", formatBytes(report.payload_bytes)],
        ["内容 SHA-256", report.payload_sha256 || "—", "mono"]
      ], null));

      box.appendChild(card);
      card.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function renderExtractFailure(snapshot) {
      var error = (snapshot && snapshot.error) || {};
      var info = errorInfo(error.code, error.message);
      var box = $("extractResult");
      box.innerHTML = "";

      var card = el("div", "card");
      var head = el("div", "result-head");
      head.appendChild(el("div", "result-icon bad", "!"));
      var headText = el("div");
      headText.appendChild(el("h2", "result-title", info.title));
      headText.appendChild(el("p", "result-sub", info.body));
      head.appendChild(headText);
      card.appendChild(head);

      if (info.list) {
        var notice = el("div", "notice notice-info");
        var ul = el("ul");
        info.list.forEach(function (item) { ul.appendChild(el("li", null, item)); });
        notice.appendChild(ul);
        card.appendChild(notice);
      }

      if (info.advice) {
        card.appendChild(el("p", "notice notice-warn", "怎么办：" + info.advice));
      }

      box.appendChild(card);
      card.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  // ------------------------------------------------------------------ 启动

  document.addEventListener("DOMContentLoaded", function () {
    initTabs();
    checkHealth();
    initEmbed();
    initExtract();
  });
})();

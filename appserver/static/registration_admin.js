require([
    "jquery",
    "splunkjs/mvc/simplexml/ready!"
], function($) {
    "use strict";

    var base = "/en-US/splunkd/__raw/services/ctf_registration";
    var selectedId = null;
    var defaultImage = "/static/app/SA-ctf_registration/images/default-ctf.svg";
    var maxImageBytes = 5 * 1024 * 1024;
    var allowedImageTypes = ["image/png", "image/jpeg", "image/webp"];

    function message(text, error) {
        $("#ctfr-admin-message").text(text || "").toggleClass("error", !!error).show();
    }

    function prettyTime(value) {
        if (!value) { return "—"; }
        var date = new Date(value);
        return isNaN(date.getTime()) ? value : date.toLocaleString();
    }

    function toLocalInput(value) {
        if (!value) { return ""; }
        var d = new Date(value);
        if (isNaN(d.getTime())) { return ""; }
        var pad = function(n) { return String(n).padStart(2, "0"); };
        return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
            "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
    }

    function toIso(value) {
        if (!value) { return ""; }
        var d = new Date(value);
        return isNaN(d.getTime()) ? value : d.toISOString();
    }

    function resetForm() {
        selectedId = null;
        $("#ctfr-admin-form")[0].reset();
        $("#ctfr-ctf-id").prop("readonly", false);
        $("#ctfr-enabled").prop("checked", true);
        $("#ctfr-allow-updates").prop("checked", true);
        $("#ctfr-participant-roles").val("ctf_competitor");
        $("#ctfr-image-url").val(defaultImage);
        $("#ctfr-image-file").val("");
        $("#ctfr-image-preview").attr("src", defaultImage);
        $("#ctfr-upload-status").text("");
        $("#ctfr-editor-title").text("Create CTF");
        $("#ctfr-roster-panel").hide();
    }

    function populateForm(event) {
        selectedId = event.ctf_id;
        $("#ctfr-editor-title").text("Edit " + (event.name || event.ctf_id));
        $("#ctfr-ctf-id").val(event.ctf_id).prop("readonly", true);
        $("#ctfr-name").val(event.name || "");
        $("#ctfr-short-description").val(event.short_description || "");
        $("#ctfr-description").val(event.description || "");
        $("#ctfr-image-url").val(event.image_url || defaultImage);
        $("#ctfr-image-file").val("");
        $("#ctfr-image-preview").attr("src", event.image_url || defaultImage);
        $("#ctfr-upload-status").text("");
        $("#ctfr-registration-opens").val(toLocalInput(event.registration_opens));
        $("#ctfr-registration-closes").val(toLocalInput(event.registration_closes));
        $("#ctfr-event-starts").val(toLocalInput(event.event_starts));
        $("#ctfr-event-ends").val(toLocalInput(event.event_ends));
        $("#ctfr-search-url").val(event.search_url || "");
        $("#ctfr-search-desc").val(event.search_url_desc || "");
        $("#ctfr-scoring-url").val(event.scoring_url || "");
        $("#ctfr-participant-roles").val(event.participant_roles || "ctf_competitor");
        $("#ctfr-enabled").prop("checked", String(event.enabled).toLowerCase() === "true");
        $("#ctfr-allow-updates").prop("checked", String(event.allow_updates).toLowerCase() !== "false");
        $("#ctfr-roster-panel").show();
        loadRoster(event.ctf_id);
    }

    function loadEvents() {
        $.ajax({url: base + "/admin/events", method: "GET", dataType: "json", cache: false})
            .done(function(data) {
                var body = $("#ctfr-events-table tbody").empty();
                (data.events || []).forEach(function(event) {
                    var tr = $("<tr>").attr("data-ctf-id", event.ctf_id);
                    $("<td>").text(event.name || event.ctf_id).appendTo(tr);
                    $("<td>").text(event.registration_state || "").appendTo(tr);
                    $("<td>").text(event.event_state || "").appendTo(tr);
                    $("<td>").text(prettyTime(event.event_starts)).appendTo(tr);
                    $("<td>").append(
                        $("<button>").addClass("btn").attr("type", "button").text("Edit")
                    ).appendTo(tr);
                    tr.data("event", event);
                    body.append(tr);
                });
            })
            .fail(function(xhr) {
                message("Unable to load events: " + (xhr.responseText || xhr.statusText), true);
            });
    }

    function loadRoster(ctfId) {
        if (!ctfId) { return; }
        $.ajax({
            url: base + "/admin/roster",
            method: "GET",
            dataType: "json",
            data: {ctf_id: ctfId},
            cache: false
        }).done(function(data) {
            var body = $("#ctfr-roster-table tbody").empty();
            (data.users || []).forEach(function(row) {
                var tr = $("<tr>");
                $("<td>").text(row.Username || "").appendTo(tr);
                $("<td>").text(row.DisplayUsername || "").appendTo(tr);
                $("<td>").text(row.Team || "").appendTo(tr);
                $("<td>").text(row.Email || "").appendTo(tr);
                body.append(tr);
            });
            $("#ctfr-roster-summary").text(
                (data.count || 0) + " registered user(s), " + (data.teams || 0) + " team(s)"
            );
        }).fail(function(xhr) {
            message("Unable to load roster: " + (xhr.responseText || xhr.statusText), true);
        });
    }


    function uploadImage(file) {
        var ctfId = ($("#ctfr-ctf-id").val() || "").trim().toLowerCase();

        if (!ctfId) {
            message("Enter the CTF ID before uploading an image.", true);
            $("#ctfr-image-file").val("");
            return;
        }
        if (allowedImageTypes.indexOf(file.type) === -1) {
            message("Image must be PNG, JPEG, or WebP.", true);
            $("#ctfr-image-file").val("");
            return;
        }
        if (file.size > maxImageBytes) {
            message("Image exceeds the 5 MB upload limit.", true);
            $("#ctfr-image-file").val("");
            return;
        }

        var reader = new FileReader();
        reader.onload = function(event) {
            $("#ctfr-upload-status").text("Uploading…");
            $.ajax({
                url: base + "/admin/upload-image",
                method: "POST",
                dataType: "json",
                data: {
                    ctf_id: ctfId,
                    image_data: event.target.result
                }
            }).done(function(resp) {
                $("#ctfr-image-url").val(resp.image_url);
                $("#ctfr-image-preview").attr("src", resp.image_url + "?v=" + Date.now());
                $("#ctfr-upload-status").text(
                    "Uploaded " + resp.filename + " (" + Math.round(resp.size / 1024) + " KB)"
                );
                message("Image uploaded. Save the CTF to associate it with the event.", false);
            }).fail(function(xhr) {
                var m = xhr.responseJSON && xhr.responseJSON.message ?
                    xhr.responseJSON.message : (xhr.responseText || xhr.statusText);
                $("#ctfr-upload-status").text("");
                message("Image upload failed: " + m, true);
            });
        };
        reader.readAsDataURL(file);
    }

    $("#ctfr-image-file").on("change", function() {
        var file = this.files && this.files[0];
        if (file) {
            uploadImage(file);
        }
    });

    $("#ctfr-use-default-image").on("click", function() {
        $("#ctfr-image-file").val("");
        $("#ctfr-image-url").val(defaultImage);
        $("#ctfr-image-preview").attr("src", defaultImage);
        $("#ctfr-upload-status").text("Using the default CTF image.");
    });

    $("#ctfr-image-url").on("change", function() {
        $("#ctfr-image-preview").attr("src", $(this).val() || defaultImage);
    });

    $("#ctfr-events-table").on("click", "button", function() {
        populateForm($(this).closest("tr").data("event"));
    });

    $("#ctfr-new-event").on("click", resetForm);

    $("#ctfr-refresh-roster").on("click", function() {
        loadRoster(selectedId);
    });

    $("#ctfr-admin-form").on("submit", function(event) {
        event.preventDefault();

        var payload = {
            ctf_id: $("#ctfr-ctf-id").val(),
            name: $("#ctfr-name").val(),
            short_description: $("#ctfr-short-description").val(),
            description: $("#ctfr-description").val(),
            image_url: $("#ctfr-image-url").val(),
            registration_opens: toIso($("#ctfr-registration-opens").val()),
            registration_closes: toIso($("#ctfr-registration-closes").val()),
            event_starts: toIso($("#ctfr-event-starts").val()),
            event_ends: toIso($("#ctfr-event-ends").val()),
            search_url: $("#ctfr-search-url").val(),
            search_url_desc: $("#ctfr-search-desc").val(),
            scoring_url: $("#ctfr-scoring-url").val(),
            participant_roles: $("#ctfr-participant-roles").val(),
            enabled: $("#ctfr-enabled").is(":checked") ? "true" : "false",
            allow_updates: $("#ctfr-allow-updates").is(":checked") ? "true" : "false"
        };

        $.ajax({
            url: base + "/admin/event",
            method: "POST",
            dataType: "json",
            data: payload
        }).done(function(resp) {
            message(resp.message || "CTF event saved.", false);
            selectedId = resp.ctf_id;
            loadEvents();
        }).fail(function(xhr) {
            var m = xhr.responseJSON && xhr.responseJSON.message ?
                xhr.responseJSON.message : (xhr.responseText || xhr.statusText);
            message("Save failed: " + m, true);
        });
    });

    resetForm();
    loadEvents();
});

require([
    "jquery",
    "splunkjs/mvc/simplexml/ready!"
], function($) {
    "use strict";

    var base = "/en-US/splunkd/__raw/services/ctf_registration";
    var defaultImage = "/static/app/SA-ctf_registration/images/default-ctf.svg";
    var eventsById = {};

    function showMessage(text, isError) {
        $("#ctfr-message").text(text || "").toggleClass("error", !!isError).show();
    }

    function prettyTime(value) {
        if (!value) { return "—"; }
        var date = new Date(value);
        return isNaN(date.getTime()) ? value : date.toLocaleString();
    }

    function badgeText(event) {
        if (event.registration_state === "OPEN") { return "REGISTRATION OPEN"; }
        if (event.event_state === "IN_PROGRESS") { return "IN PROGRESS"; }
        if (event.registration_state === "UPCOMING") { return "COMING SOON"; }
        if (event.registered) { return "REGISTERED"; }
        return "REGISTRATION CLOSED";
    }

    function renderEvents(data) {
        var grid = $("#ctfr-events").empty();
        eventsById = {};

        (data.events || []).forEach(function(event) {
            eventsById[event.ctf_id] = event;

            var card = $("<article>")
                .addClass("ctfr-event-card")
                .attr("data-ctf-id", event.ctf_id)
                .attr("tabindex", "0")
                .attr("role", "button")
                .attr("aria-label", "Open " + (event.name || event.ctf_id));
            var image = $("<img>")
                .addClass("ctfr-event-image")
                .attr("alt", event.name || "CTF event")
                .attr("src", event.image_url || defaultImage)
                .on("error", function() { $(this).attr("src", defaultImage); });

            var body = $("<div>").addClass("ctfr-event-body");
            $("<div>").addClass("ctfr-badge").text(badgeText(event)).appendTo(body);
            $("<h2>").text(event.name || event.ctf_id).appendTo(body);
            $("<p>").addClass("ctfr-short").text(event.short_description || "").appendTo(body);
            $("<div>")
                .addClass("ctfr-card-start")
                .text("Starts " + prettyTime(event.event_starts))
                .appendTo(body);

            var button = $("<button>")
                .addClass("btn btn-primary")
                .attr("type", "button")
                .attr("data-ctf-id", event.ctf_id)
                .text(event.registration_state === "OPEN" ? (event.registered ? "View / Update" : "Register") : "View Details");
            body.append(button);

            card.append(image, body);
            grid.append(card);
        });

        if (!(data.events || []).length) {
            grid.append($("<div>").addClass("ctfr-empty").text("There are no upcoming CTF events."));
        }
    }

    function openEvent(ctfId) {
        var event = eventsById[ctfId];
        if (!event) { return; }

        $(".ctfr-event-card").removeClass("is-selected");
        $(".ctfr-event-card[data-ctf-id='" + event.ctf_id.replace(/'/g, "\'") + "']").addClass("is-selected");
        $("#ctfr-detail").show();
        $("#ctfr-detail-image")
            .off("error.ctfrDetail")
            .on("error.ctfrDetail", function() { $(this).attr("src", defaultImage); })
            .attr("src", event.image_url || defaultImage);
        $("#ctfr-detail-name").text(event.name || event.ctf_id);
        $("#ctfr-detail-description").text(event.description || event.short_description || "");
        $("#ctfr-detail-registration-window").text(prettyTime(event.registration_opens) + " → " + prettyTime(event.registration_closes));
        $("#ctfr-detail-event-window").text(prettyTime(event.event_starts) + " → " + prettyTime(event.event_ends));
        $("#ctfr-detail-state").text(badgeText(event));

        var record = event.registration || {};
        $("#ctfr-id").val(event.ctf_id);
        $("#ctfr-display").val(record.DisplayUsername || "");
        $("#ctfr-team").val(record.Team || "");
        $("#ctfr-first").val(record.FirstName || "");
        $("#ctfr-last").val(record.LastName || "");
        $("#ctfr-email").val(record.Email || "");

        var canEdit = event.registration_state === "OPEN" && (!event.registered || event.allow_updates);
        $("#ctfr-form :input").prop("disabled", !canEdit);
        $("#ctfr-id").prop("disabled", false);

        if (event.registered) {
            $("#ctfr-submit").text("Update Registration");
            $("#ctfr-registration-note").text(
                canEdit ? "You are registered. You may update your information while registration remains open."
                        : "You are registered. Registration changes are closed."
            );
        } else if (event.registration_state === "OPEN") {
            $("#ctfr-submit").text("Register");
            $("#ctfr-registration-note").text("Registration is open for this CTF.");
        } else if (event.registration_state === "UPCOMING") {
            $("#ctfr-registration-note").text("Registration has not opened yet.");
        } else {
            $("#ctfr-registration-note").text("Registration is closed for this CTF.");
        }

        document.getElementById("ctfr-detail").scrollIntoView({behavior: "smooth", block: "start"});
    }

    function loadEvents() {
        $.ajax({url: base + "/events", method: "GET", dataType: "json", cache: false})
            .done(renderEvents)
            .fail(function(xhr) {
                showMessage("Unable to load CTF events: " + (xhr.responseText || xhr.statusText), true);
            });
    }

    $("#ctfr-events").on("click", "button[data-ctf-id]", function(event) {
        event.stopPropagation();
        openEvent($(this).attr("data-ctf-id"));
    });

    $("#ctfr-events").on("click", ".ctfr-event-card[data-ctf-id]", function() {
        openEvent($(this).attr("data-ctf-id"));
    });

    $("#ctfr-events").on("keydown", ".ctfr-event-card[data-ctf-id]", function(event) {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            openEvent($(this).attr("data-ctf-id"));
        }
    });

    $("#ctfr-detail-close").on("click", function() {
        $("#ctfr-detail").hide();
        $(".ctfr-event-card").removeClass("is-selected");
    });

    $("#ctfr-form").on("submit", function(event) {
        event.preventDefault();
        $("#ctfr-submit").prop("disabled", true);

        $.ajax({
            url: base + "/register",
            method: "POST",
            dataType: "json",
            data: $(this).serialize()
        }).done(function(data) {
            var msg = data.message || "Registration saved.";
            if (data.roles_added && data.roles_added.length) {
                msg += " CTF access role(s) added: " + data.roles_added.join(", ") + ".";
            }
            showMessage(msg, false);
            loadEvents();
        }).fail(function(xhr) {
            var message = xhr.responseJSON && xhr.responseJSON.message ?
                xhr.responseJSON.message : (xhr.responseText || xhr.statusText);
            showMessage("Registration failed: " + message, true);
        }).always(function() {
            $("#ctfr-submit").prop("disabled", false);
        });
    });

    loadEvents();
});

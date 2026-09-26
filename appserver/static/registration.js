require([
    "jquery",
    "splunkjs/mvc/simplexml/ready!"
], function($) {
    "use strict";

    var base = "/en-US/splunkd/__raw/servicesNS/nobody/SA-ctf_registration/ctf_registration";

    function showMessage(text, isError) {
        var el = $("#ctfr-message");
        el.text(text || "").toggleClass("error", !!isError).show();
    }

    function prettyTime(value) {
        if (!value) { return "—"; }
        var date = new Date(value);
        return isNaN(date.getTime()) ? value : date.toLocaleString();
    }

    function applyStatus(data) {
        $("#ctfr-state").text(data.state || "UNKNOWN");
        $("#ctfr-event").text(data.event || "CTF Event");
        $("#ctfr-opens").text(prettyTime(data.opens_at));
        $("#ctfr-closes").text(prettyTime(data.closes_at));
        $("#ctfr-user").text(data.username || "—");

        var record = data.registration || {};
        $("#ctfr-display").val(record.DisplayUsername || "");
        $("#ctfr-team").val(record.Team || "");
        $("#ctfr-first").val(record.FirstName || "");
        $("#ctfr-last").val(record.LastName || "");
        $("#ctfr-email").val(record.Email || "");

        var canEdit = !!data.can_register;
        $("#ctfr-form :input").prop("disabled", !canEdit);

        if (data.registered) {
            $("#ctfr-submit").text("Update Registration");
        } else {
            $("#ctfr-submit").text("Register");
        }

        if (!canEdit) {
            if (data.state === "UPCOMING") {
                showMessage("Registration has not opened yet.", false);
            } else if (data.state === "CLOSED") {
                showMessage(data.registered ? "Registration is closed. Your registration is read-only." : "Registration is closed.", false);
            } else if (data.state === "DISABLED") {
                showMessage("Registration is currently disabled by the event administrator.", false);
            }
        } else if (data.registered) {
            showMessage("You are registered. You may update your information until registration closes.", false);
        } else {
            $("#ctfr-message").hide();
        }
    }

    function loadStatus() {
        $.ajax({ url: base + "/status", method: "GET", dataType: "json", cache: false })
            .done(applyStatus)
            .fail(function(xhr) {
                showMessage("Unable to load registration status: " + (xhr.responseText || xhr.statusText), true);
                $("#ctfr-form :input").prop("disabled", true);
            });
    }

    $("#ctfr-form").on("submit", function(event) {
        event.preventDefault();
        $("#ctfr-submit").prop("disabled", true);
        $.ajax({
            url: base + "/register",
            method: "POST",
            dataType: "json",
            data: $(this).serialize()
        }).done(function(data) {
            showMessage(data.message || "Registration saved.", false);
            loadStatus();
        }).fail(function(xhr) {
            var message = xhr.responseJSON && xhr.responseJSON.message ? xhr.responseJSON.message : (xhr.responseText || xhr.statusText);
            showMessage("Registration failed: " + message, true);
        }).always(function() {
            $("#ctfr-submit").prop("disabled", false);
        });
    });

    loadStatus();
});

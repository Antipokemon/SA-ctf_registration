require([
    "jquery",
    "splunkjs/mvc/simplexml/ready!"
], function($) {
    "use strict";

    var base = "/en-US/splunkd/__raw/servicesNS/nobody/SA-ctf_registration/ctf_registration";

    function message(text, error) {
        $("#ctfr-admin-message").text(text || "").toggleClass("error", !!error).show();
    }

    function loadConfig() {
        $.ajax({ url: base + "/admin/config", method: "GET", dataType: "json", cache: false })
            .done(function(data) {
                $("#ctfr-admin-state").text(data.state || "UNKNOWN");
                $("#ctfr-enabled").prop("checked", !!data.enabled);
                $("#ctfr-event-name").val(data.event || "");
                $("#ctfr-open-time").val(data.opens_at || "");
                $("#ctfr-close-time").val(data.closes_at || "");
                $("#ctfr-search-url").val(data.search_url || "");
                $("#ctfr-search-desc").val(data.search_url_desc || "");
                $("#ctfr-scoring-url").val(data.scoring_url || "");
                $("#ctfr-allow-updates").prop("checked", !!data.allow_updates);
            })
            .fail(function(xhr) { message("Unable to load configuration: " + (xhr.responseText || xhr.statusText), true); });
    }

    function loadRoster() {
        $.ajax({ url: base + "/admin/roster", method: "GET", dataType: "json", cache: false })
            .done(function(data) {
                var body = $("#ctfr-roster-table tbody").empty();
                (data.users || []).forEach(function(row) {
                    var tr = $("<tr>");
                    $("<td>").text(row.Username || "").appendTo(tr);
                    $("<td>").text(row.DisplayUsername || "").appendTo(tr);
                    $("<td>").text(row.Team || "").appendTo(tr);
                    $("<td>").text(row.Email || "").appendTo(tr);
                    body.append(tr);
                });
                $("#ctfr-roster-summary").text((data.count || 0) + " registered user(s), " + (data.teams || 0) + " team(s)");
            })
            .fail(function(xhr) { message("Unable to load roster: " + (xhr.responseText || xhr.statusText), true); });
    }

    $("#ctfr-admin-form").on("submit", function(event) {
        event.preventDefault();
        var data = $(this).serializeArray();
        data.push({name: "enabled", value: $("#ctfr-enabled").is(":checked") ? "true" : "false"});
        data.push({name: "allow_updates", value: $("#ctfr-allow-updates").is(":checked") ? "true" : "false"});
        $.ajax({ url: base + "/admin/config", method: "POST", dataType: "json", data: $.param(data) })
            .done(function(resp) { message(resp.message || "Configuration saved.", false); loadConfig(); })
            .fail(function(xhr) {
                var m = xhr.responseJSON && xhr.responseJSON.message ? xhr.responseJSON.message : (xhr.responseText || xhr.statusText);
                message("Save failed: " + m, true);
            });
    });

    $("#ctfr-refresh-roster").on("click", loadRoster);
    loadConfig();
    loadRoster();
});

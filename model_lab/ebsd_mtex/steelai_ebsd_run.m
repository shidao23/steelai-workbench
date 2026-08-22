function steelai_ebsd_run(configPath)
%STEELAI_EBSD_RUN Non-interactive MTEX entry point for SteelAI Workbench.
% The source EBSD file is opened read-only. All artifacts are written to the
% configured SteelAI output directory.

config = jsondecode(fileread(configPath));
outputDir = char(config.output_dir);
if ~isfolder(outputDir)
    mkdir(outputDir);
end
failurePath = fullfile(outputDir, 'failure.json');
if isfile(failurePath)
    delete(failurePath);
end

logPath = fullfile(outputDir, 'analysis.log');
diary(logPath);
cleanupDiary = onCleanup(@() diary('off'));
set(groot, 'DefaultFigureVisible', 'off');

fprintf('SteelAI EBSD pilot started: %s\n', char(datetime('now')));
fprintf('Input: %s\n', char(config.input_file));
fprintf('Output: %s\n', outputDir);

if exist('EBSD', 'class') ~= 8
    addpath(char(config.mtex_root));
    startup_mtex;
end

try
    ebsd = EBSD.load(char(config.input_file), ...
        'interface', 'ctf', 'convertSpatial2EulerReferenceFrame');
    target = ebsd(char(config.target_phase));
    retained = ebsd(char(config.retained_phase));
    if isempty(target)
        error('SteelAI:MissingTargetPhase', ...
            'Target phase was not found: %s', char(config.target_phase));
    end

    grainAngle = double(config.grain_angle_deg) * degree;
    minPixels = double(config.min_grain_pixels);
    [grains, target.grainId, target.mis2mean] = calcGrains(target, ...
        'angle', grainAngle, 'minPixel', minPixels);
    grainsForPlot = smooth(grains, double(config.grain_smoothing_iterations));

    grainArea = area(grains);
    grainArea = grainArea(:);
    equivalentDiameter = 2 .* sqrt(grainArea ./ pi);
    grainPixels = grains.numPixel;
    grainPixels = grainPixels(:);
    grainGOS = grains.GOS ./ degree;
    grainGOS = grainGOS(:);
    grainIds = grains.id;
    grainIds = grainIds(:);
    isBoundary = grains.isBoundary;
    isBoundary = isBoundary(:);
    grainTable = table(grainIds, grainPixels, grainArea, equivalentDiameter, ...
        grainGOS, isBoundary, 'VariableNames', ...
        {'grain_id', 'num_pixels', 'area_um2', 'equivalent_diameter_um', ...
        'gos_deg', 'touches_scan_boundary'});
    writetable(grainTable, fullfile(outputDir, 'grains.csv'));

    boundary = grains.boundary;
    boundaryAngles = boundary.misorientation.angle(:) ./ degree;
    boundaryLengths = boundary.segLength(:);
    validBoundary = isfinite(boundaryAngles) & isfinite(boundaryLengths);
    boundaryAngles = boundaryAngles(validBoundary);
    boundaryLengths = boundaryLengths(validBoundary);
    boundaryTable = table(boundaryAngles, boundaryLengths, ...
        'VariableNames', {'misorientation_deg', 'segment_length_um'});
    writetable(boundaryTable, fullfile(outputDir, 'boundaries.csv'));

    lagbMask = boundaryAngles >= double(config.lagb_min_deg) & ...
        boundaryAngles < double(config.hagb_min_deg);
    hagbMask = boundaryAngles >= double(config.hagb_min_deg);
    classifiedBoundaryLength = sum(boundaryLengths(lagbMask | hagbMask));
    if classifiedBoundaryLength > 0
        lagbFraction = 100 * sum(boundaryLengths(lagbMask)) / classifiedBoundaryLength;
        hagbFraction = 100 * sum(boundaryLengths(hagbMask)) / classifiedBoundaryLength;
    else
        lagbFraction = NaN;
        hagbFraction = NaN;
    end

    targetGrid = target.gridify;
    kam = targetGrid.KAM('order', double(config.kam_order), ...
        'threshold', double(config.kam_threshold_deg) * degree) ./ degree;
    kamValues = kam(isfinite(kam));

    totalPoints = length(ebsd);
    indexedPoints = length(ebsd('indexed'));
    targetPoints = length(target);
    retainedPoints = length(retained);
    interiorDiameters = equivalentDiameter(~isBoundary & isfinite(equivalentDiameter));
    allDiameters = equivalentDiameter(isfinite(equivalentDiameter));

    summary = struct;
    summary.schema_version = '1.0';
    summary.status = 'completed';
    summary.run_id = char(config.run_id);
    summary.sample_id = char(config.sample_id);
    summary.analysis_scope = char(config.analysis_scope);
    summary.input_file = char(config.input_file);
    summary.raw_files_read_only = logical(config.raw_files_read_only);
    if isfield(config, 'mtex_version_expected')
        summary.mtex_version = char(config.mtex_version_expected);
    else
        summary.mtex_version = '6.1.0';
    end
    summary.total_points = totalPoints;
    summary.indexed_points = indexedPoints;
    summary.indexed_fraction_percent = safePercent(indexedPoints, totalPoints);
    summary.target_phase = char(config.target_phase);
    summary.target_phase_points = targetPoints;
    summary.target_phase_fraction_of_indexed_percent = safePercent(targetPoints, indexedPoints);
    summary.retained_phase = char(config.retained_phase);
    summary.retained_phase_points = retainedPoints;
    summary.retained_phase_fraction_of_indexed_percent = safePercent(retainedPoints, indexedPoints);
    summary.grain_count = length(grains);
    summary.interior_grain_count = sum(~isBoundary);
    summary.mean_equivalent_diameter_um_all = safeMean(allDiameters);
    summary.median_equivalent_diameter_um_all = safeMedian(allDiameters);
    summary.mean_equivalent_diameter_um_interior = safeMean(interiorDiameters);
    summary.median_equivalent_diameter_um_interior = safeMedian(interiorDiameters);
    summary.mean_kam_deg = safeMean(kamValues);
    summary.median_kam_deg = safeMedian(kamValues);
    summary.lagb_length_fraction_percent = lagbFraction;
    summary.hagb_length_fraction_percent = hagbFraction;
    summary.parameters = config;
    summary.warnings = {
        'Orientation grains are not automatically equivalent to martensite blocks, packets, or prior-austenite grains.';
        'Retained FCC fraction requires phase-identification and acquisition-quality validation.';
        'Grain size, KAM, LAGB, and HAGB values depend on the recorded analysis parameters.'
    };
    writeJson(fullfile(outputDir, 'summary.json'), summary);

    createPhaseMap(ebsd, outputDir);
    createIpfMap(target, grainsForPlot, outputDir);
    createGrainMap(target, grainsForPlot, outputDir);
    createKamMap(targetGrid, kam, grainsForPlot, outputDir);
    createGrainHistogram(allDiameters, outputDir);

    manifest = struct;
    manifest.schema_version = '1.0';
    manifest.status = 'completed';
    manifest.created_at = char(datetime('now', 'Format', 'yyyy-MM-dd''T''HH:mm:ssXXX'));
    manifest.config_file = configPath;
    manifest.summary_file = fullfile(outputDir, 'summary.json');
    manifest.grain_table = fullfile(outputDir, 'grains.csv');
    manifest.boundary_table = fullfile(outputDir, 'boundaries.csv');
    manifest.figures = {'phase_map.png', 'ipf_map.png', 'grain_map.png', ...
        'kam_map.png', 'grain_size_distribution.png'};
    writeJson(fullfile(outputDir, 'run_manifest.json'), manifest);
    fprintf('SteelAI EBSD pilot completed successfully.\n');
catch exception
    failure = struct;
    failure.schema_version = '1.0';
    failure.status = 'failed';
    failure.identifier = exception.identifier;
    failure.message = exception.message;
    failure.report = getReport(exception, 'extended', 'hyperlinks', 'off');
    writeJson(fullfile(outputDir, 'failure.json'), failure);
    fprintf(2, '%s\n', failure.report);
    rethrow(exception);
end
end


function value = safePercent(numerator, denominator)
if denominator > 0
    value = 100 * double(numerator) / double(denominator);
else
    value = NaN;
end
end


function value = safeMean(values)
if isempty(values)
    value = NaN;
else
    value = mean(values, 'omitnan');
end
end


function value = safeMedian(values)
if isempty(values)
    value = NaN;
else
    value = median(values, 'omitnan');
end
end


function writeJson(path, payload)
text = jsonencode(payload, 'PrettyPrint', true);
fileId = fopen(path, 'w', 'n', 'UTF-8');
if fileId < 0
    error('SteelAI:OutputWriteFailed', 'Unable to open output file: %s', path);
end
cleanupFile = onCleanup(@() fclose(fileId));
fwrite(fileId, text, 'char');
end


function createPhaseMap(ebsd, outputDir)
figure('Color', 'w');
plot(ebsd);
exportgraphics(gcf, fullfile(outputDir, 'phase_map.png'), 'Resolution', 220);
close(gcf);
end


function createIpfMap(target, grains, outputDir)
key = ipfHSVKey(target);
key.inversePoleFigureDirection = vector3d.Z;
colors = key.orientation2color(target.orientations);
figure('Color', 'w');
plot(target, colors, 'micronbar', 'on');
hold on;
plot(grains.boundary, 'lineColor', 'k', 'lineWidth', 0.7);
hold off;
exportgraphics(gcf, fullfile(outputDir, 'ipf_map.png'), 'Resolution', 220);
close(gcf);
end


function createGrainMap(target, grains, outputDir)
figure('Color', 'w');
plot(target, target.orientations, 'micronbar', 'on');
hold on;
plot(grains.boundary, 'lineColor', 'k', 'lineWidth', 0.8);
hold off;
exportgraphics(gcf, fullfile(outputDir, 'grain_map.png'), 'Resolution', 220);
close(gcf);
end


function createKamMap(targetGrid, kam, grains, outputDir)
figure('Color', 'w');
plot(targetGrid, kam, 'micronbar', 'on');
mtexColorbar('title', 'KAM (degree)');
hold on;
plot(grains.boundary, 'lineColor', 'k', 'lineWidth', 0.5);
hold off;
exportgraphics(gcf, fullfile(outputDir, 'kam_map.png'), 'Resolution', 220);
close(gcf);
end


function createGrainHistogram(diameters, outputDir)
figure('Color', 'w');
histogram(diameters, 30);
xlabel('Equivalent diameter (um)');
ylabel('Grain count');
title('BCC orientation-grain size distribution');
grid on;
exportgraphics(gcf, fullfile(outputDir, 'grain_size_distribution.png'), 'Resolution', 220);
close(gcf);
end

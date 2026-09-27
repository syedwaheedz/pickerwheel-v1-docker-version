/**
 * PickerWheel UI - Clean Implementation
 * Focused on proper wheel mechanics and UI
 */

// Plain fetch() never times out on its own - if a request never gets a
// response (server thread exhaustion, a stuck DB query, a dropped
// connection that never errors), an awaited fetch in the spin flow would
// hang forever with no way for its try/finally to run, leaving the wheel
// stuck on "SPINNING..." with the button disabled until the page is
// reloaded. This wraps fetch with an AbortController-based timeout so a
// hung request fails after a bounded wait instead of hanging indefinitely.
function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    return fetch(url, { ...options, signal: controller.signal })
        .finally(() => clearTimeout(timeoutId));
}

class PickerWheelUI {
    constructor() {
        // Use relative path for API calls to work with any host/port
        this.apiBaseUrl = '/api';
        this.wheel = null;
        this.wheelInner = null;
        this.spinButton = null;
        this.wheelPointer = null;
        this.currentRotation = 0;
        this.isSpinning = false;
        this.availablePrizes = [];
        this.segments = [];
        this.segmentAngle = 0;
        
        // Audio system
        this.audioContext = null;
        this.tickSound = null;
        this.tickInterval = null;
        
        // 🎵 Enhanced Audio System with Asset Sounds
        this.audioElements = {
            spinSound: null,
            winSound: null,
            rareWinSound: null
        };
        
        // Settings
        this.soundEnabled = true;
        this.effectsEnabled = true;
        
        // Daily prizes log state
        this.dailyPrizesLog = [];
        this.logDisplayHidden = false;
        
        // Mobile responsiveness
        this.isMobile = this.detectMobile();
        
        this.init();
    }

    // 📱 MOBILE DETECTION
    detectMobile() {
        return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) ||
               window.innerWidth <= 768;
    }

    // 🎨 GET COMBO EMOJI DISPLAY
    getComboEmojiDisplay(prizeName) {
        const comboMappings = {
            'smartwatch + mini cooler': '⌚+❄️',
            'power bank + neckband': '🔋+🎧', 
            'earbuds and g.speaker': '🎧+🔊'
        };
        
        const normalizedName = prizeName.toLowerCase().trim();
        return comboMappings[normalizedName] || null;
    }

    // 📱 GET MOBILE-OPTIMIZED SIZES
    getMobileSizes() {
        if (this.isMobile) {
            return {
                wheelSize: Math.min(window.innerWidth * 0.9, 450), // 90% of screen width, max 450px
                fontSize: {
                    emoji: '16px',
                    text: '10px',  // Reduced from 12px for better fit
                    modal: '4rem'
                },
                spinButton: '60px'
            };
        } else {
            return {
                wheelSize: 400,
                fontSize: {
                    emoji: '14px',
                    text: '9px',   // Reduced from 11px for better fit
                    modal: '3rem'
                },
                spinButton: '50px'
            };
        }
    }

    async init() {
        try {
            dlog('🎯 Initializing PickerWheel UI...');
            
            // Load theme configuration first
            if (window.themeManager) {
                await window.themeManager.loadConfig();
                window.themeManager.applyTheme();
            }
            
            // Get DOM elements
            this.wheel = document.getElementById('wheel');
            this.wheelInner = document.getElementById('wheelInner');
            this.spinButton = document.getElementById('spinButton');
            this.wheelPointer = document.getElementById('wheelPointer');
            this.wheelSparks = document.getElementById('wheelSparks');
            this.loadingOverlay = document.getElementById('loadingOverlay');
            this.modalOverlay = document.getElementById('modalOverlay');
            this.soundToggle = document.getElementById('soundToggle');
            this.effectsToggle = document.getElementById('effectsToggle');

            if (!this.wheel || !this.wheelInner || !this.spinButton) {
                throw new Error('Required DOM elements not found');
            }

            // Setup event listeners
            this.setupEventListeners();
            
            // Initialize audio system
            this.initAudio();
            
            // Load settings
            this.loadSettings();
            
            // Load initial data
            await this.loadAvailablePrizes();
            await this.loadStats();
            
            // Create wheel
            this.createWheel();
            
            // Initialize daily prizes log
            this.initializeDailyPrizesLog();
            
            dlog('✅ PickerWheel UI initialized successfully');
            
        } catch (error) {
            console.error('❌ Failed to initialize UI:', error);
            this.showError('Failed to initialize the contest. Please refresh the page.');
        }
    }

    setupEventListeners() {
        // Spin button
        this.spinButton.addEventListener('click', () => this.spin());
        
        // Modal close
        const closeModal = document.getElementById('closeModal');
        if (closeModal) {
            closeModal.addEventListener('click', () => this.closeModal());
        }
        
        // Close modal on overlay click
        if (this.modalOverlay) {
            this.modalOverlay.addEventListener('click', (e) => {
                if (e.target === this.modalOverlay) {
                    this.closeModal();
                }
            });
        }
        
        // Control buttons
        if (this.soundToggle) {
            this.soundToggle.addEventListener('click', () => this.toggleSound());
        }
        
        if (this.effectsToggle) {
            this.effectsToggle.addEventListener('click', () => this.toggleEffects());
        }

        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.code === 'Space' && !this.isSpinning) {
                e.preventDefault();
                this.spin();
            } else if (e.code === 'Escape') {
                this.closeModal();
            }
        });
    }

    initAudio() {
        try {
            // Initialize Web Audio API
            this.audioContext = new (window.AudioContext || window.webkitAudioContext)();
            dlog('🔊 Audio system initialized');
            
            // 🎵 Load sound assets
            this.loadSoundAssets();
        } catch (error) {
            dwarn('⚠️ Audio not supported:', error);
        }
    }
    
    loadSoundAssets() {
        try {
            // Create audio elements for different sounds
            this.audioElements.spinSound = new Audio('sounds/spin-sound.mp3');
            this.audioElements.winSound = new Audio('sounds/win-sound.mp3');
            this.audioElements.rareWinSound = new Audio('sounds/rare-win-sound.mp3');
            
            // Configure audio elements
            Object.values(this.audioElements).forEach(audio => {
                if (audio) {
                    audio.preload = 'auto';
                    audio.volume = 0.7; // Set default volume
                    
                    // Handle loading events
                    audio.addEventListener('canplaythrough', () => {
                        dlog('🎵 Sound loaded:', audio.src.split('/').pop());
                    });
                    
                    audio.addEventListener('error', (e) => {
                        dwarn('⚠️ Failed to load sound:', audio.src.split('/').pop(), e);
                    });
                    
                    // Handle browser audio policy restrictions
                    audio.addEventListener('play', () => {
                        dlog('🎵 Audio playing:', audio.src.split('/').pop());
                    });
                }
            });
            
            // Add click handler to enable audio context (required by browsers)
            this.enableAudioOnFirstInteraction();
            
            dlog('🎵 Loading sound assets...');
        } catch (error) {
            dwarn('⚠️ Failed to initialize sound assets:', error);
        }
    }
    
    enableAudioOnFirstInteraction() {
        const enableAudio = () => {
            // Resume audio context if suspended
            if (this.audioContext && this.audioContext.state === 'suspended') {
                this.audioContext.resume().then(() => {
                    dlog('🔊 Audio context enabled on user interaction');
                });
            }
            
            // Test load all audio elements
            Object.values(this.audioElements).forEach(audio => {
                if (audio) {
                    audio.load(); // Reload to ensure they're ready
                }
            });
            
            // Remove this listener after first interaction
            document.removeEventListener('click', enableAudio);
            document.removeEventListener('touchstart', enableAudio);
            dlog('🎵 Audio system fully enabled');
        };
        
        // Listen for first user interaction
        document.addEventListener('click', enableAudio);
        document.addEventListener('touchstart', enableAudio);
    }

    createTickSound(frequency = 800, duration = 0.1, volume = 0.3) {
        if (!this.audioContext) return null;

        try {
            const oscillator = this.audioContext.createOscillator();
            const gainNode = this.audioContext.createGain();
            
            // Connect nodes
            oscillator.connect(gainNode);
            gainNode.connect(this.audioContext.destination);
            
            // Configure oscillator
            oscillator.type = 'square';
            oscillator.frequency.setValueAtTime(frequency, this.audioContext.currentTime);
            
            // Configure gain (volume) with quick fade
            gainNode.gain.setValueAtTime(volume, this.audioContext.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, this.audioContext.currentTime + duration);
            
            return { oscillator, gainNode };
        } catch (error) {
            dwarn('⚠️ Failed to create tick sound:', error);
            return null;
        }
    }

    playTickSound(volume = 0.3) {
        const sound = this.createTickSound(800, 0.1, volume);
        if (sound) {
            sound.oscillator.start();
            sound.oscillator.stop(this.audioContext.currentTime + 0.1);
        }
    }

    startTickingSound() {
        if (!this.audioContext || !this.soundEnabled) return;

        // Resume audio context if suspended (required by some browsers)
        if (this.audioContext.state === 'suspended') {
            this.audioContext.resume();
        }

        const wheelDuration = 6200; // Total wheel animation duration
        const soundDuration = 5000; // Sound stops 1.2 seconds before wheel stops
        const startTime = Date.now();
        let tickCount = 0;
        const initialInterval = 60; // Start with faster ticks
        const finalInterval = 600; // End with much slower ticks

        const tick = () => {
            const elapsed = Date.now() - startTime;
            
            // Stop sound before wheel animation completes or if spinning stopped
            if (elapsed >= soundDuration || !this.isSpinning) {
                this.tickInterval = null;
                dlog('🔇 Sound faded out before wheel stops');
                return;
            }

            // Calculate progress based on sound duration (not wheel duration)
            const progress = elapsed / soundDuration;
            
            // Calculate volume fade with dramatic fade-out at the end
            // Use exponential curve for more realistic fade
            const volumeFactor = Math.max(0.05, Math.pow(1 - progress, 2));
            const volume = 0.4 * volumeFactor;

            // Play tick sound
            this.playTickSound(volume);

            tickCount++;

            // Calculate next interval based on progress (gradually slow down)
            // Use cubic easing to match the wheel's deceleration curve
            const easedProgress = 1 - Math.pow(1 - progress, 3);
            let nextInterval = initialInterval + (finalInterval - initialInterval) * easedProgress;
            
            // In the final 20% of sound duration, make ticks much slower and quieter
            if (progress > 0.8) {
                const finalPhase = (progress - 0.8) / 0.2; // 0 to 1 in final 20%
                nextInterval = nextInterval + (800 * finalPhase); // Up to 800ms between final ticks
            }

            // Schedule next tick
            this.tickInterval = setTimeout(tick, nextInterval);
        };

        // Start ticking
        tick();
    }

    stopTickingSound() {
        if (this.tickInterval) {
            clearTimeout(this.tickInterval);
            this.tickInterval = null;
            dlog('🔇 Ticking sound stopped');
        }
    }
    
    // 🎵 Enhanced Sound Methods
    playSpinSound() {
        if (!this.soundEnabled || !this.audioElements.spinSound) return;
        
        try {
            this.audioElements.spinSound.currentTime = 0; // Reset to beginning
            this.audioElements.spinSound.play().catch(e => {
                dwarn('⚠️ Failed to play spin sound:', e);
            });
            dlog('🎵 Playing spin sound');
        } catch (error) {
            dwarn('⚠️ Error playing spin sound:', error);
        }
    }
    
    playWinSound(category = 'common') {
        if (!this.soundEnabled) return;
        
        try {
            let soundToPlay;
            
            // Choose sound based on prize category
            if (category === 'rare' || category === 'ultra_rare') {
                soundToPlay = this.audioElements.rareWinSound;
                dlog('🎵 Playing rare win celebration sound');
            } else {
                soundToPlay = this.audioElements.winSound;
                dlog('🎵 Playing win celebration sound');
            }
            
            if (soundToPlay) {
                soundToPlay.currentTime = 0; // Reset to beginning
                soundToPlay.play().catch(e => {
                    dwarn('⚠️ Failed to play win sound:', e);
                });
            }
        } catch (error) {
            dwarn('⚠️ Error playing win sound:', error);
        }
    }
    
    stopAllSounds() {
        try {
            // Stop all audio elements
            Object.values(this.audioElements).forEach(audio => {
                if (audio && !audio.paused) {
                    audio.pause();
                    audio.currentTime = 0;
                }
            });
            
            // Stop ticking sound
            this.stopTickingSound();
            
            dlog('🔇 All sounds stopped');
        } catch (error) {
            dwarn('⚠️ Error stopping sounds:', error);
        }
    }

    startSpinningEffects() {
        if (!this.effectsEnabled) return;
        
        // Start pointer vibration
        if (this.wheelPointer) {
            this.wheelPointer.classList.add('vibrating');
        }
        
        // Start friction sparks at pointer contact
        if (this.wheelSparks) {
            this.wheelSparks.classList.add('spinning');
        }
        
        dlog('🎪 Started spinning effects - pointer vibration and friction sparks');
    }

    stopSpinningEffects() {
        // Stop pointer vibration
        if (this.wheelPointer) {
            this.wheelPointer.classList.remove('vibrating');
        }
        
        // Stop friction sparks
        if (this.wheelSparks) {
            this.wheelSparks.classList.remove('spinning');
        }
        
        dlog('🎪 Stopped spinning effects');
    }

    toggleSound() {
        this.soundEnabled = !this.soundEnabled;
        
        if (this.soundToggle) {
            if (this.soundEnabled) {
                this.soundToggle.classList.remove('disabled');
                this.soundToggle.title = 'Disable Sound';
            } else {
                this.soundToggle.classList.add('disabled');
                this.soundToggle.title = 'Enable Sound';
                // Stop any currently playing sound
                this.stopAllSounds();
            }
        }
        
        // Save preference
        localStorage.setItem('picker_wheel_sound', this.soundEnabled);
        dlog('🔊 Sound', this.soundEnabled ? 'enabled' : 'disabled');
    }

    toggleEffects() {
        this.effectsEnabled = !this.effectsEnabled;
        
        if (this.effectsToggle) {
            if (this.effectsEnabled) {
                this.effectsToggle.classList.remove('disabled');
                this.effectsToggle.title = 'Disable Effects';
            } else {
                this.effectsToggle.classList.add('disabled');
                this.effectsToggle.title = 'Enable Effects';
                // Stop any currently running effects
                this.stopSpinningEffects();
            }
        }
        
        // Save preference
        localStorage.setItem('picker_wheel_effects', this.effectsEnabled);
        dlog('✨ Effects', this.effectsEnabled ? 'enabled' : 'disabled');
    }

    loadSettings() {
        // Load sound preference
        const savedSound = localStorage.getItem('picker_wheel_sound');
        if (savedSound !== null) {
            this.soundEnabled = savedSound === 'true';
        }

        // Load effects preference
        const savedEffects = localStorage.getItem('picker_wheel_effects');
        if (savedEffects !== null) {
            this.effectsEnabled = savedEffects === 'true';
        }

        // Update button states
        if (this.soundToggle) {
            if (this.soundEnabled) {
                this.soundToggle.classList.remove('disabled');
                this.soundToggle.title = 'Disable Sound';
            } else {
                this.soundToggle.classList.add('disabled');
                this.soundToggle.title = 'Enable Sound';
            }
        }
        
        if (this.effectsToggle) {
            if (this.effectsEnabled) {
                this.effectsToggle.classList.remove('disabled');
                this.effectsToggle.title = 'Disable Effects';
            } else {
                this.effectsToggle.classList.add('disabled');
                this.effectsToggle.title = 'Enable Effects';
            }
        }

        dlog('⚙️ Settings loaded - Sound:', this.soundEnabled, 'Effects:', this.effectsEnabled);
    }

    async loadAvailablePrizes() {
        try {
            dlog('📦 Loading unique prizes for wheel display...');
            
            // Add cache buster to force fresh data
            const cacheBuster = new Date().getTime();
            const response = await fetch(`${this.apiBaseUrl}/prizes/wheel-display?t=${cacheBuster}`, {
                cache: 'no-cache',
                headers: {
                    'Cache-Control': 'no-cache, no-store, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0'
                }
            });
            const data = await response.json();
            
            if (!data.success) {
                throw new Error(data.error || 'Failed to load prizes');
            }
            
            // Normalize prize data - map prize_id to id for consistency
            this.availablePrizes = (data.prizes || []).map(prize => ({
                ...prize,
                id: prize.prize_id || prize.id,  // Ensure 'id' is always available
                category: prize.category_name || prize.category  // Normalize category name
            }));
            
            dlog(`✅ Loaded ${this.availablePrizes.length} unique prizes (deduplicated by backend)`);
            if (data.original_count) {
                dlog(`   (Original: ${data.original_count} items → Unique: ${this.availablePrizes.length})`);
            }
            dlog('Wheel prizes:', this.availablePrizes.map((p, i) => `${i + 1}. ${p.name} (${p.category})`));
            
        } catch (error) {
            console.error('❌ Failed to load prizes:', error);
            throw error;
        }
    }

    async loadStats() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/stats`);
            const data = await response.json();
            
            if (data.success) {
                this.updateStatsDisplay(data.stats);
            }
        } catch (error) {
            dwarn('⚠️ Failed to load stats:', error);
        }
    }

    updateStatsDisplay(stats) {
        const statsGrid = document.getElementById('statsGrid');
        if (!statsGrid) return;

        statsGrid.innerHTML = `
            <div class="stat-item">
                <span class="stat-value">${stats.total_wins || 0}</span>
                <span class="stat-label">Total Wins Today</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${this.availablePrizes.length}</span>
                <span class="stat-label">Available Prizes</span>
            </div>
            <div class="stat-item">
                <span class="stat-value">${stats.unique_users || 0}</span>
                <span class="stat-label">Participants</span>
            </div>
        `;
    }

    createWheel() {
        if (this.availablePrizes.length === 0) {
            this.showError('No prizes available today. Please try again tomorrow!');
            return;
        }

        dlog('🎡 Creating wheel with', this.availablePrizes.length, 'prizes');

        // Clear existing segments
        this.wheelInner.innerHTML = '';
        
        // Calculate equal segment angle for all prizes
        this.segmentAngle = 360 / this.availablePrizes.length;
        
        // Create segments with equal sizes
        this.segments = this.availablePrizes.map((prize, index) => {
            const color = this.getPrizeColor(prize.category, index);
            return {
                ...prize,
                index,
                angle: this.segmentAngle,
                startAngle: index * this.segmentAngle,
                endAngle: (index + 1) * this.segmentAngle,
                color: color,
                textColor: this.getTextColor(prize.category, color)
            };
        });

        // Debug: Log segment mapping
        dlog('🎡 Segment mapping:');
        this.segments.forEach((segment, index) => {
            dlog(`  ${index}: ${segment.name} (ID: ${segment.id}) - ${segment.startAngle.toFixed(1)}° to ${segment.endAngle.toFixed(1)}°`);
        });
        
        // Debug: Log available prizes by budget tier
        const breakdown = this.availablePrizes.reduce((acc, prize) => {
            const tier = prize.budget_tier || 'unknown';
            acc[tier] = (acc[tier] || 0) + 1;
            return acc;
        }, {});
        dlog('📊 Available prizes by budget tier:', breakdown);

        // Create SVG wheel for precise segments
        this.createSVGWheel();

        dlog('✅ Wheel created with', this.segments.length, 'equal segments');
    }

    createSVGWheel() {
        const sizes = this.getMobileSizes();
        const wheelSize = sizes.wheelSize;
        const centerX = wheelSize / 2;
        const centerY = wheelSize / 2;
        const radius = wheelSize / 2 - 10;

        // Create SVG element
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', wheelSize);
        svg.setAttribute('height', wheelSize);
        svg.setAttribute('viewBox', `0 0 ${wheelSize} ${wheelSize}`);
        svg.style.width = '100%';
        svg.style.height = '100%';

        // Slices first, then labels on top so separators never cross text
        this.segments.forEach(segment => {
            this.createSVGSegment(svg, segment, centerX, centerY, radius);
        });
        this.segments.forEach(segment => {
            this.addSegmentText(svg, segment, centerX, centerY, radius);
        });

        // Concentric rings: a fine highlight on the rim and a dark hub ring
        // with a pink edge that frames the centre SPIN button
        const rim = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        rim.setAttribute('cx', centerX);
        rim.setAttribute('cy', centerY);
        rim.setAttribute('r', radius - 1);
        rim.setAttribute('fill', 'none');
        rim.setAttribute('stroke', 'rgba(255, 214, 232, 0.6)');
        rim.setAttribute('stroke-width', radius * 0.012);
        svg.appendChild(rim);

        const hub = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        hub.setAttribute('cx', centerX);
        hub.setAttribute('cy', centerY);
        hub.setAttribute('r', radius * 0.3);
        hub.setAttribute('fill', '#14030C');
        hub.setAttribute('stroke', '#FF2B86');
        hub.setAttribute('stroke-width', radius * 0.016);
        svg.appendChild(hub);

        // Clear and add SVG to wheel
        this.wheelInner.innerHTML = '';
        this.wheelInner.appendChild(svg);
    }

    createSVGSegment(svg, segment, centerX, centerY, radius) {
        // Convert angles to radians, starting from top (12 o'clock)
        const startAngleRad = (segment.startAngle - 90) * (Math.PI / 180);
        const endAngleRad = (segment.endAngle - 90) * (Math.PI / 180);
        
        // Calculate arc endpoints
        const x1 = centerX + radius * Math.cos(startAngleRad);
        const y1 = centerY + radius * Math.sin(startAngleRad);
        const x2 = centerX + radius * Math.cos(endAngleRad);
        const y2 = centerY + radius * Math.sin(endAngleRad);
        
        // Determine if we need a large arc
        const largeArcFlag = segment.angle > 180 ? 1 : 0;
        
        // Create SVG path
        const pathData = [
            `M ${centerX} ${centerY}`,
            `L ${x1} ${y1}`,
            `A ${radius} ${radius} 0 ${largeArcFlag} 1 ${x2} ${y2}`,
            'Z'
        ].join(' ');
        
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathData);
        const separatorColor = 'rgba(255, 214, 232, 0.55)';
        const separatorWidth = radius * 0.008;
        path.setAttribute('fill', segment.color);
        path.setAttribute('stroke', separatorColor);
        path.setAttribute('stroke-width', separatorWidth);
        path.setAttribute('stroke-linejoin', 'round');
        path.setAttribute('data-prize-id', segment.id);
        path.setAttribute('data-segment-index', segment.index);
        path.style.cursor = 'pointer';
        
        // Add hover effect
        path.addEventListener('mouseenter', () => {
            path.setAttribute('stroke-width', separatorWidth * 2.5);
            path.setAttribute('stroke', '#FFFFFF');
        });
        
        path.addEventListener('mouseleave', () => {
            path.setAttribute('stroke-width', separatorWidth);
            path.setAttribute('stroke', separatorColor);
        });
        
        svg.appendChild(path);
    }

    addSegmentText(svg, segment, centerX, centerY, radius) {
        const SVG_NS = 'http://www.w3.org/2000/svg';
        const midAngle = (segment.startAngle + segment.endAngle) / 2;
        const sliceRad = (segment.angle * Math.PI) / 180;

        // Rotate a group so the segment's centre line runs along +x. Labels on
        // the left half are flipped 180° so they read upright at rest.
        const flip = midAngle > 180;
        const dir = flip ? -1 : 1;
        const groupRotation = midAngle - 90 + (flip ? 180 : 0);
        const group = document.createElementNS(SVG_NS, 'g');
        group.setAttribute('transform', `rotate(${groupRotation} ${centerX} ${centerY})`);
        group.setAttribute('pointer-events', 'none');

        // Icon near the rim, where the slice is widest, counter-rotated so it
        // stands upright at rest (combo emojis kept for legacy combo prizes)
        const iconX = centerX + dir * radius * 0.86;
        const iconSize = Math.min(radius * 0.09, radius * 0.86 * sliceRad * 0.6);
        const comboEmoji = this.getComboEmojiDisplay(segment.name);
        const icon = document.createElementNS(SVG_NS, 'text');
        icon.setAttribute('x', iconX);
        icon.setAttribute('y', centerY);
        icon.setAttribute('text-anchor', 'middle');
        icon.setAttribute('dominant-baseline', 'central');
        icon.setAttribute('font-size', iconSize);
        icon.setAttribute('fill', segment.textColor);
        icon.setAttribute('class', 'wheel-icon');
        icon.setAttribute('transform', `rotate(${-groupRotation} ${iconX} ${centerY})`);
        if (comboEmoji) {
            icon.textContent = comboEmoji;
        } else {
            icon.setAttribute('font-family', "'Material Symbols Outlined'");
            icon.textContent = this.getPrizeIcon(segment.name);
        }
        group.appendChild(icon);

        // Full prize name on up to 3 lines, centred in the band between the
        // hub and the icon. Font size is capped by the slice width at that
        // radius (so 3 lines fit) and by the band length (so the longest
        // line fits) - names are never abbreviated.
        const lines = this.wrapPrizeLabel(segment.name);
        // 3-line labels sit a little further out, where the slice is wider
        const labelRadius = radius * (lines.length === 3 ? 0.62 : 0.58);
        const bandLength = radius * 0.4;
        const longest = Math.max(...lines.map(line => line.length));
        const lineHeight = lines.length === 3 ? 1.04 : 1.1;
        const fontSize = Math.min(
            radius * ({ 1: 0.055, 2: 0.048, 3: 0.046 }[lines.length] || 0.036),
            (labelRadius * sliceRad * 0.86) / (lines.length * lineHeight),
            bandLength / (longest * 0.62)
        );

        const label = document.createElementNS(SVG_NS, 'text');
        label.setAttribute('class', 'wheel-label');
        label.setAttribute('text-anchor', 'middle');
        label.setAttribute('dominant-baseline', 'central');
        label.setAttribute('font-size', fontSize);
        label.setAttribute('fill', segment.textColor);
        if (segment.textColor.toUpperCase() === '#FFFFFF') {
            label.setAttribute('stroke', 'rgba(20, 0, 10, 0.45)');
            label.setAttribute('stroke-width', fontSize * 0.14);
        }
        lines.forEach((line, i) => {
            const tspan = document.createElementNS(SVG_NS, 'tspan');
            tspan.setAttribute('x', centerX + dir * labelRadius);
            tspan.setAttribute('y', centerY + (i - (lines.length - 1) / 2) * fontSize * lineHeight);
            tspan.textContent = line;
            label.appendChild(tspan);
        });
        group.appendChild(label);

        svg.appendChild(group);
    }

    // Wrap a prize name into at most `maxLines` lines on word boundaries,
    // widening the per-line budget rather than ever truncating a word.
    wrapPrizeLabel(name, maxLines = 3) {
        const words = String(name || '').toUpperCase().split(/\s+/).filter(Boolean);
        if (words.length === 0) return [''];

        for (let limit = 11; ; limit++) {
            const lines = [];
            for (const word of words) {
                const last = lines[lines.length - 1];
                if (last !== undefined && `${last} ${word}`.length <= limit) {
                    lines[lines.length - 1] = `${last} ${word}`;
                } else {
                    lines.push(word);
                }
            }
            if (lines.length <= maxLines) return lines;
        }
    }

    // ==========================================
    // INCREMENTAL UPDATE METHODS
    // For real-time wheel updates without full rebuild
    // ==========================================

    /**
     * Update prizes and rebuild wheel with optional animation
     * Called by wheel-realtime.js for real-time updates
     */
    updatePrizes(newPrizes, animate = true) {
        if (!newPrizes || newPrizes.length === 0) {
            dwarn('No prizes to update');
            return false;
        }

        // If spinning, queue update
        if (this.isSpinning) {
            this._pendingPrizeUpdate = newPrizes;
            dlog('⏳ Update queued - wheel is spinning');
            return false;
        }

        const oldPrizes = [...this.availablePrizes];
        const changes = this.detectPrizeChanges(oldPrizes, newPrizes);

        dlog('🔄 Prize changes detected:', {
            added: changes.added.length,
            removed: changes.removed.length,
            modified: changes.modified.length
        });

        // Format prizes
        this.availablePrizes = newPrizes.map(prize => ({
            id: prize.prize_id || prize.id,
            prize_id: prize.prize_id || prize.id,
            name: prize.name || prize.prize_name,
            category: prize.category_name || prize.category,
            category_name: prize.category_name || prize.category,
            emoji: prize.emoji || '🎁',
            is_enabled: prize.is_enabled !== false,
            remaining_quantity: prize.remaining_quantity || 0
        }));

        // Rebuild wheel with animation
        if (animate) {
            this.animateWheelRebuild();
        } else {
            this.createWheel();
        }

        return true;
    }

    /**
     * Detect changes between old and new prizes
     */
    detectPrizeChanges(oldPrizes, newPrizes) {
        const oldIds = new Set(oldPrizes.map(p => p.id || p.prize_id));
        const newIds = new Set(newPrizes.map(p => p.id || p.prize_id));
        const oldMap = new Map(oldPrizes.map(p => [p.id || p.prize_id, p]));
        const newMap = new Map(newPrizes.map(p => [p.id || p.prize_id, p]));

        const added = [];
        const removed = [];
        const modified = [];

        // Find added prizes
        newIds.forEach(id => {
            if (!oldIds.has(id)) {
                added.push(newMap.get(id));
            }
        });

        // Find removed prizes
        oldIds.forEach(id => {
            if (!newIds.has(id)) {
                removed.push(oldMap.get(id));
            }
        });

        // Find modified prizes
        newIds.forEach(id => {
            if (oldIds.has(id)) {
                const oldPrize = oldMap.get(id);
                const newPrize = newMap.get(id);
                if (this.isPrizeModified(oldPrize, newPrize)) {
                    modified.push({ old: oldPrize, new: newPrize });
                }
            }
        });

        return { added, removed, modified };
    }

    /**
     * Check if a prize has been modified
     */
    isPrizeModified(oldPrize, newPrize) {
        return (
            oldPrize.name !== (newPrize.name || newPrize.prize_name) ||
            oldPrize.is_enabled !== (newPrize.is_enabled !== false) ||
            oldPrize.emoji !== (newPrize.emoji || '🎁')
        );
    }

    /**
     * Animate wheel rebuild with fade effect
     */
    animateWheelRebuild() {
        if (!this.wheelInner) {
            this.createWheel();
            return;
        }

        // Fade out
        this.wheelInner.style.transition = 'opacity 0.2s ease-out';
        this.wheelInner.style.opacity = '0.5';

        // Rebuild after fade out
        setTimeout(() => {
            this.createWheel();
            
            // Fade in
            requestAnimationFrame(() => {
                this.wheelInner.style.opacity = '1';
                setTimeout(() => {
                    this.wheelInner.style.transition = '';
                }, 200);
            });
        }, 200);
    }

    /**
     * Get current prize count
     */
    getPrizeCount() {
        return this.availablePrizes?.length || 0;
    }

    /**
     * Get prize by ID
     */
    getPrizeById(prizeId) {
        return this.availablePrizes?.find(p => (p.id || p.prize_id) === prizeId);
    }

    /**
     * Check if wheel needs update based on new prizes
     */
    needsUpdate(newPrizes) {
        if (!newPrizes || !this.availablePrizes) return true;
        if (newPrizes.length !== this.availablePrizes.length) return true;
        
        // Check for any changes
        const changes = this.detectPrizeChanges(this.availablePrizes, newPrizes);
        return changes.added.length > 0 || 
               changes.removed.length > 0 || 
               changes.modified.length > 0;
    }

    // ==========================================
    // END INCREMENTAL UPDATE METHODS
    // ==========================================

    getPrizeColor(category, index) {
        // Get colors from ThemeManager if available, otherwise use defaults
        let colors;

        if (window.themeManager && window.themeManager.activeTheme?.wheel?.colors) {
            colors = window.themeManager.getWheelColors();
        } else {
            // Built-in Neon palette (an active event theme can override it)
            colors = ['#1B0510', '#E50065', '#2A0716', '#FF4FA3', '#22040F', '#FF2B86'];
        }

        // Palettes alternate dark/bright. With an odd number of prizes the last
        // slice would land next to slice 0 in the same tone, right under the
        // pointer - bridge that seam with a blend of the first two colors.
        const count = this.availablePrizes.length;
        if (count % 2 === 1 && colors.length % 2 === 0 && index === count - 1) {
            return this.blendHex(colors[0], colors[1]);
        }

        return colors[index % colors.length];
    }

    blendHex(a, b) {
        const parse = hex => {
            let h = (hex || '#000000').replace('#', '');
            if (h.length === 3) h = h.split('').map(c => c + c).join('');
            return h.slice(0, 6).match(/.{2}/g).map(part => parseInt(part, 16));
        };
        const [ra, ga, ba] = parse(a);
        const [rb, gb, bb] = parse(b);
        const mix = (x, y) => Math.round((x + y) / 2).toString(16).padStart(2, '0');
        return `#${mix(ra, rb)}${mix(ga, gb)}${mix(ba, bb)}`.toUpperCase();
    }

    getTextColor(category, segmentColor) {
        // Light wheel shades need dark text, others use white
        const lightColors = ['#FF9EC4', '#FF6FA8'];
        if (segmentColor && lightColors.includes(segmentColor.toUpperCase())) {
            return '#1a1a2e';  // Dark text for light backgrounds
        }
        return '#FFFFFF';  // White text for all other backgrounds
    }

    // Material Symbols (Outlined) icon per prize, keyed by the name with
    // everything but letters/digits stripped, so "Air Cooler", "AIRCOOLER"
    // and "air-cooler" all match. Unmapped prizes get a generic gift icon.
    // Every icon used here must also be in the icon_names list of the font
    // <link> in index.html (the font is subsetted to keep it small).
    static PRIZE_ICON_MAP = {
        aircooler: 'mode_fan',
        '32inchtv': 'tv',
        '32inchestv': 'tv',
        washingmachine: 'local_laundry_service',
        hometheatre: 'theaters',
        luggagebag: 'luggage',
        govobuds: 'earbuds',
        smartaudiosunglasses: 'eyeglasses',
        smartaudio: 'spatial_audio',
        sunglasses: 'eyeglasses',
        boultq5bluetoothspeaker: 'speaker',
        g5gamesupgaminghandheld: 'sports_esports',
        g5gameandsupgaminghandheld: 'sports_esports',
        soundbar: 'soundbar',
        screenguardbackcover: 'smartphone',
        screenguardandbackcover: 'smartphone',
        wiredearphones: 'headphones',
        neckband: 'headset_mic',
        powerbank: 'battery_charging_full',
        smartwatch: 'watch',
        dinnerset: 'dinner_dining',
        casseroleset: 'soup_kitchen',
        cassoroleset: 'soup_kitchen',
        meethaset: 'cake',
        laptopstand: 'laptop',
        massagegun: 'spa',
        inductionstove: 'cooking',
        '2in1juicer': 'blender',
    };

    getPrizeIcon(prizeName) {
        const key = (prizeName || '').toLowerCase().replace(/[^a-z0-9]/g, '');
        return PickerWheelUI.PRIZE_ICON_MAP[key] || 'redeem';
    }

    async spin() {
        if (this.isSpinning) {
            dlog('⚠️ Already spinning');
            return;
        }

        if (this.availablePrizes.length === 0) {
            this.showError('No prizes available today!');
            return;
        }

        dlog('🎯 Starting spin...');
        this.isSpinning = true;
        this.spinButton.disabled = true;
        this.spinButton.textContent = 'SPINNING...';
        
        // 🎵 Play spin sound at the start
        this.playSpinSound();
        
        // Prevent page shake during spin
        document.body.classList.add('spinning');

        try {
            dlog('🔍 === SIMPLIFIED SPIN FLOW ===');
            
            // === STEP 1: BACKEND DETERMINES AVAILABLE PRIZE ===
            dlog('📡 Step 1: Backend determining available prize...');
            const availablePrize = await this.getBackendSelectedPrize();
            
            // === STEP 2: FRONTEND CALCULATES WHEEL ROTATION ===
            dlog('🔄 Step 2: Calculating wheel rotation...');
            const rotationData = await this.calculateWheelRotation(availablePrize);
            
            // === STEP 3: ANIMATE WHEEL TO TARGET POSITION ===
            dlog('🎡 Step 3: Animating wheel to target position...');
            await this.animateWheelToPosition(rotationData.totalRotation);
            
            // === STEP 4: VERIFY ALIGNMENT ===
            dlog('✅ Step 4: Verifying wheel alignment...');
            const alignment = this.verifyWheelAlignment(availablePrize, rotationData.targetSegment);
            
            // === STEP 5: BACKEND CONFIRMS AND AWARDS PRIZE ===
            dlog('🏆 Step 5: Confirming prize award with backend...');
            const awardedPrize = await this.confirmPrizeWithBackend(availablePrize, rotationData);
            
            // === STEP 6: DISPLAY RESULT ===
            dlog('🎉 Step 6: Displaying result...');
            this.showCelebration(awardedPrize);
            
            dlog('✅ Spin completed successfully!');
            
        } catch (error) {
            console.error('❌ Spin failed:', error);
            this.showError(error.message || 'Spin failed. Please try again.');
        } finally {
            this.isSpinning = false;
            this.spinButton.disabled = false;
            this.spinButton.textContent = 'SPIN';
            
            // Stop all effects in case of error
            this.stopTickingSound();
            document.body.classList.remove('spinning');
        }
    }


    calculateExactRotation(targetSegmentIndex) {
        // Calculate the exact rotation needed to land on target segment
        const segmentAngle = 360 / this.segments.length;
        
        // Calculate the center of the target segment
        const targetSegmentCenter = targetSegmentIndex * segmentAngle + (segmentAngle / 2);
        
        // ORIGINAL WORKING LOGIC: To align the target segment with the pointer,
        // we need the wheel to be positioned so that the target segment center is at 0°.
        // This means we need to rotate the wheel by: -targetSegmentCenter
        // But since we want positive rotation, we use: 360° - targetSegmentCenter
        let targetFinalPosition = 360 - targetSegmentCenter;
        
        // Normalize to 0-360 range
        targetFinalPosition = targetFinalPosition % 360;
        if (targetFinalPosition < 0) targetFinalPosition += 360;
        
        // Get current wheel position (normalized to 0-360)
        const currentPosition = this.currentRotation % 360;
        
        // Calculate the minimum rotation needed to reach target
        let rotationNeeded = targetFinalPosition - currentPosition;
        
        // Ensure we always rotate in the positive direction and add exciting spins
        if (rotationNeeded <= 0) {
            rotationNeeded += 360; // Complete at least one full rotation
        }
        
        // Add exciting full rotations (8-12 additional spins for visual effect)
        // CRITICAL: Must be whole numbers to maintain precision
        const extraSpins = Math.floor(8 + Math.random() * 4);
        const totalRotationIncrement = rotationNeeded + (extraSpins * 360);
        
        // Calculate the final absolute rotation
        const finalAbsoluteRotation = this.currentRotation + totalRotationIncrement;
        
        dlog(`🎯 ROTATION CALCULATION (CORRECTED):`);
        dlog(`   Target segment: ${targetSegmentIndex}`);
        dlog(`   Segment center angle: ${targetSegmentCenter}°`);
        dlog(`   Target final position: ${targetFinalPosition}° (CORRECTED: segment center at pointer)`);
        dlog(`   Current position: ${currentPosition}° (absolute: ${this.currentRotation}°)`);
        dlog(`   Rotation needed: ${rotationNeeded}°`);
        dlog(`   Extra spins: ${extraSpins.toFixed(1)} (${(extraSpins * 360)}°)`);
        dlog(`   Total rotation increment: ${totalRotationIncrement}°`);
        dlog(`   Final absolute rotation: ${finalAbsoluteRotation}°`);
        
        // Verify our math
        const predictedFinalPosition = finalAbsoluteRotation % 360;
        dlog(`🔍 Predicted final position: ${predictedFinalPosition}° (should be ~${targetFinalPosition}°)`);
        
        // Double-check: which segment will be at pointer?
        const predictedSegment = Math.floor(predictedFinalPosition / segmentAngle) % this.segments.length;
        dlog(`🔍 Predicted segment at pointer: ${predictedSegment} (should be ${targetSegmentIndex})`);
        
        return finalAbsoluteRotation;
    }

    async animateWheelToPosition(targetRotation) {
        return new Promise((resolve) => {
            dlog(`🎡 Starting wheel animation to ${targetRotation}°`);
            
            // Start ticking sound
            this.startTickingSound();
            
            // Reset any existing transition
            this.wheelInner.style.transition = 'none';
            this.wheelInner.style.transform = `rotate(${this.currentRotation}deg)`;
            
            // Force reflow
            this.wheelInner.offsetHeight;
            
            // Apply exciting rotation animation with longer duration
            this.wheelInner.style.transition = 'transform 6s cubic-bezier(0.23, 1, 0.32, 1)';
            this.wheelInner.style.transform = `rotate(${targetRotation}deg)`;
            
            // Update current rotation for next spin
            this.currentRotation = targetRotation;
            
            dlog(`🎡 Wheel rotating to ${targetRotation}° (final position: ${this.currentRotation}°)`);
            
            // Stop ticking sound after animation
            setTimeout(() => {
                this.stopTickingSound();
                dlog('🎡 Wheel animation completed');
                resolve();
            }, 6000);
        });
    }

    // === PHASE 2: CALCULATE EXACT ROTATION ANGLE ===
    calculatePreciseRotation(serverDecision) {
        dlog(`🎯 Calculating precise rotation for sector ${serverDecision.sector_index}...`);
        
        const targetSectorIndex = serverDecision.sector_index;
        const sectorCenter = serverDecision.sector_center;
        
        // Verify the prize exists on our wheel
        const wheelPrize = this.segments[targetSectorIndex];
        if (!wheelPrize || wheelPrize.id !== serverDecision.prize.id) {
            throw new Error(`Mapping error: Server prize ${serverDecision.prize.id} doesn't match wheel segment ${targetSectorIndex}`);
        }
        
        dlog(`✅ Verified mapping: Sector ${targetSectorIndex} = ${wheelPrize.name}`);
        
        // CORRECT LOGIC: Let's think step by step
        // 
        // GOAL: Bring sector center from its current position to the pointer (0°)
        // 
        // EXAMPLE: Sector center is at 211.30°, we want it at 0°
        // 
        // METHOD 1 - Think about wheel rotation:
        // - Currently: sector is at 211.30° position on the wheel
        // - We want: sector to be at 0° position (pointer)
        // - So we need to rotate the wheel by: -211.30° (counterclockwise)
        // - In CSS terms (clockwise positive): 360° - 211.30° = 148.70°
        // 
        // METHOD 2 - Think about final wheel position:
        // - After rotation, we want the sector center to align with pointer
        // - The wheel's final rotation should be such that: 
        //   (sectorCenter + wheelRotation) % 360 = 0
        // - So: wheelRotation = -sectorCenter = 360° - sectorCenter
        
        const rotationNeededFromZero = (360 - sectorCenter) % 360;
        
        dlog(`🔧 CORRECT LOGIC DEBUG:`);
        dlog(`   Sector center: ${sectorCenter}°`);
        dlog(`   To bring to pointer: rotate wheel by ${rotationNeededFromZero}°`);
        dlog(`   Verification: (${sectorCenter}° + ${rotationNeededFromZero}°) % 360 = ${(sectorCenter + rotationNeededFromZero) % 360}° (should be 0°)`);
        
        
        // Add exciting multiple rotations (8-12 spins) - MUST be integer to avoid floating point errors
        const totalSpins = Math.floor(8 + Math.random() * 4);
        
        // NOW: Calculate how much to rotate from current position
        // 
        // Current wheel is at: this.currentRotation
        // We want wheel to end up at: rotationNeededFromZero (absolute position)
        // 
        // But we need to account for the current position:
        // If wheel is currently at 50° and we want it at 100°, we rotate by 50°
        // If wheel is currently at 200° and we want it at 50°, we rotate by 210° (going forward)
        
        const currentNormalized = this.currentRotation % 360;
        let rotationIncrement = rotationNeededFromZero - currentNormalized;
        
        // Always rotate in positive direction (clockwise)
        if (rotationIncrement < 0) {
            rotationIncrement += 360;
        }
        
        // CRITICAL FIX: The final rotation should be calculated correctly
        // We want the wheel to end up at rotationNeededFromZero position
        // So: finalRotation = currentRotation + extraSpins + incrementNeeded
        // Where incrementNeeded = targetPosition - currentNormalized
        
        const finalRotation = this.currentRotation + (totalSpins * 360) + rotationIncrement;
        
        // VERIFICATION: Check that our math is correct
        const expectedFinalPosition = finalRotation % 360;
        const shouldBe = rotationNeededFromZero;
        
        dlog(`🔧 MATH VERIFICATION:`);
        dlog(`   Final rotation: ${finalRotation}°`);
        dlog(`   Expected final position: ${expectedFinalPosition}°`);
        dlog(`   Should be: ${shouldBe}°`);
        dlog(`   Math correct: ${Math.abs(expectedFinalPosition - shouldBe) < 0.01 ? '✅' : '❌'}`);
        
        dlog(`🔧 FINAL CALCULATION:`);
        dlog(`   Current wheel position: ${this.currentRotation}° (normalized: ${currentNormalized}°)`);
        dlog(`   Target wheel position: ${rotationNeededFromZero}°`);
        dlog(`   Rotation increment needed: ${rotationIncrement}°`);
        dlog(`   With ${totalSpins.toFixed(1)} extra spins: ${finalRotation}°`);
        dlog(`   Final position will be: ${finalRotation % 360}° (should be ${rotationNeededFromZero}°)`);
        
        
        return {
            targetSectorIndex: targetSectorIndex,
            sectorCenter: sectorCenter,
            finalRotation: finalRotation,
            totalSpins: totalSpins,
            serverPrize: serverDecision.prize
        };
    }

    // === PHASE 3: EXECUTE SPIN ANIMATION ===
    async executeSpinAnimation(rotationData) {
        dlog(`🎡 Executing spin animation to ${rotationData.finalRotation}°...`);
        
        return new Promise((resolve) => {
            // Start ticking sound
            this.startTickingSound();
            
            // Reset any existing transition
            this.wheelInner.style.transition = 'none';
            this.wheelInner.style.transform = `rotate(${this.currentRotation}deg)`;
            
            // Force reflow
            this.wheelInner.offsetHeight;
            
            // Execute the calculated spin animation
            this.wheelInner.style.transition = 'transform 6s cubic-bezier(0.23, 1, 0.32, 1)';
            this.wheelInner.style.transform = `rotate(${rotationData.finalRotation}deg)`;
            
            // CRITICAL FIX: Get the ACTUAL CSS rotation after animation completes
            // This prevents cumulative errors from multiple spins
            const targetNormalizedPosition = rotationData.finalRotation % 360;
            this.currentRotation = targetNormalizedPosition; // Initial estimate
            
            dlog(`🎡 Wheel spinning to exact position: ${rotationData.finalRotation}°`);
            dlog(`🎯 Expected final position: ${this.currentRotation}°`);
            
            // Wait for animation completion
            setTimeout(() => {
                this.stopTickingSound();
                
                // CRITICAL: Read the actual CSS rotation to prevent cumulative errors
                const actualCSSRotation = this.getActualCSSRotation();
                if (actualCSSRotation !== null) {
                    const difference = Math.abs(actualCSSRotation - this.currentRotation);
                    dlog(`🔄 CSS SYNC: Expected ${this.currentRotation}°, Actual ${actualCSSRotation}°, Diff: ${difference}°`);
                    
                    if (difference > 1) { // If difference is significant
                        dlog(`⚠️ CORRECTING: Updating tracked rotation to match CSS`);
                        this.currentRotation = actualCSSRotation;
                    }
                }
                
                dlog('🎡 Spin animation completed');
                resolve();
            }, 6000);
        });
    }

    // === PHASE 4: VERIFY PRECISE LANDING ===
    verifyPreciseLanding(serverDecision, rotationData) {
        dlog('✅ Verifying precise landing...');
        
        const finalRotation = this.currentRotation;
        const segmentAngle = 360 / this.segments.length;
        
        // Calculate which sector is at the pointer
        const wheelPosition = finalRotation % 360;
        
        // CRITICAL FIX: The sector detection logic is wrong
        // If wheel is at 36.82°, which sector is at the pointer (0°)?
        // 
        // The wheel rotated 36.82° clockwise, so the sector that was originally at 
        // (360° - 36.82°) = 323.18° is now at the pointer
        // 
        // But we need to think differently:
        // If the wheel rotated 36.82° clockwise, then a sector that is now at the pointer (0°)
        // was originally at position (360° - 36.82°) = 323.18°
        // 
        // But sectors are positioned starting from 0°, so:
        // Sector 0 center: 7.83°
        // Sector 1 center: 23.48°
        // etc.
        // 
        // We need to find which sector center is closest to the current pointer position
        // after the rotation
        
        // After rotation, which sector center is now at the pointer (0°)?
        // We need to reverse the rotation to see which sector is there
        const originalPointerPosition = (360 - wheelPosition) % 360;
        const actualSector = Math.floor(originalPointerPosition / segmentAngle);
        const boundaryAdjusted = actualSector >= this.segments.length ? 0 : actualSector;
        
        dlog(`🔧 SECTOR DETECTION FIX:`);
        dlog(`   Wheel position: ${wheelPosition}°`);
        dlog(`   Original pointer position: ${originalPointerPosition}°`);
        dlog(`   Segment angle: ${segmentAngle}°`);
        dlog(`   Calculated sector: ${actualSector}`);
        dlog(`   Boundary adjusted: ${boundaryAdjusted}`);
        dlog(`   Browser: ${navigator.userAgent.includes('Chrome') ? 'Chrome' : navigator.userAgent.includes('Safari') ? 'Safari' : 'Other'}`);
        
        // Let's also check what the CSS transform actually shows
        const computedTransform = window.getComputedStyle(this.wheelInner).transform;
        dlog(`   CSS transform: ${computedTransform}`);
        
        // Try to extract the actual rotation from the transform matrix
        if (computedTransform && computedTransform !== 'none') {
            const matrix = computedTransform.match(/matrix\(([^)]+)\)/);
            if (matrix) {
                const values = matrix[1].split(',').map(parseFloat);
                const actualCSSRotation = Math.atan2(values[1], values[0]) * (180 / Math.PI);
                dlog(`   Actual CSS rotation: ${actualCSSRotation}°`);
                dlog(`   Expected CSS rotation: ${finalRotation % 360}°`);
                dlog(`   CSS rotation difference: ${Math.abs(actualCSSRotation - (finalRotation % 360))}°`);
            }
        }
        
        const landedPrize = this.segments[boundaryAdjusted];
        const expectedSector = serverDecision.sector_index;
        
        dlog(`🎯 Precision Landing Check:`);
        dlog(`   Server selected: Sector ${expectedSector} (${serverDecision.prize.name})`);
        dlog(`   Wheel landed on: Sector ${boundaryAdjusted} (${landedPrize ? landedPrize.name : 'Unknown'})`);
        dlog(`   Final rotation: ${finalRotation}°`);
        dlog(`   Calculated rotation: ${rotationData.finalRotation}°`);
        
        const isPerfect = boundaryAdjusted === expectedSector;
        const prizeMatches = landedPrize && landedPrize.id === serverDecision.prize.id;
        
        dlog(`   Sector match: ${isPerfect ? '✅ PERFECT' : '❌ MISMATCH'}`);
        dlog(`   Prize match: ${prizeMatches ? '✅ PERFECT' : '❌ MISMATCH'}`);
        
        return {
            isPerfect: isPerfect && prizeMatches,
            expectedSector: expectedSector,
            actualSector: boundaryAdjusted,
            landedPrize: landedPrize,
            rotationAccuracy: Math.abs(finalRotation - (rotationData.finalRotation % 360))
        };
    }

    // === UTILITY: GENERATE IDEMPOTENCY KEY ===
    generateIdempotencyKey() {
        const timestamp = Date.now();
        const random = Math.random().toString(36).substring(2, 15);
        const userId = this.getUserId();
        return `spin_${userId}_${timestamp}_${random}`;
    }

    // === PHASE 1: CLIENT STARTS RESPONSIVE SPIN ANIMATION ===
    startResponsiveSpinAnimation() {
        dlog('🎡 Starting responsive wheel animation...');
        
        // Start ticking sound
        this.startTickingSound();
        
        // Reset any existing transition
        this.wheelInner.style.transition = 'none';
        this.wheelInner.style.transform = `rotate(${this.currentRotation}deg)`;
        
        // Force reflow
        this.wheelInner.offsetHeight;
        
        // Start continuous spinning while waiting for server
        const continuousSpins = 4; // Keep spinning for 4 rotations
        const continuousRotation = this.currentRotation + (continuousSpins * 360);
        
        this.wheelInner.style.transition = 'transform 3s linear';
        this.wheelInner.style.transform = `rotate(${continuousRotation}deg)`;
        
        dlog(`🎡 Wheel spinning continuously: ${this.currentRotation}° → ${continuousRotation}°`);
        
        return {
            startTime: Date.now(),
            continuousRotation: continuousRotation,
            isResponsive: true
        };
    }

    // === PHASE 2: SERVER DECIDES PRIZE AND RESERVES IT ===
    async requestServerPrizeDecision(idempotencyKey) {
        dlog('📡 Requesting server prize decision with reservation...');
        
        const response = await fetch(`${this.apiBaseUrl}/spin/reserve`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Idempotency-Key': idempotencyKey
            },
            body: JSON.stringify({
                user_id: this.getUserId(),
                session_id: this.getSessionId(),
                client_timestamp: Date.now()
            })
        });

        const data = await response.json();
        if (!data.success) {
            throw new Error(data.error || 'Server prize decision failed');
        }

        // Verify signed response
        if (!this.verifyServerSignature(data)) {
            throw new Error('Invalid server signature - response may be tampered');
        }

        dlog('✅ Server decision received and verified:');
        dlog(`   Prize: ${data.prize.name} (ID: ${data.prize.id})`);
        dlog(`   Sector: ${data.sector_index} (angle: ${data.sector_center}°)`);
        dlog(`   Reservation: ${data.reservation_id} (TTL: ${data.reservation_ttl}s)`);
        dlog(`   Signature: ${data.signature.substring(0, 16)}...`);

        return data;
    }

    // === PHASE 3: CLIENT ANIMATES TO SERVER-SELECTED SECTOR ===
    async animateToServerSector(serverDecision, spinAnimation) {
        dlog(`🎯 Animating to server-selected sector ${serverDecision.sector_index}...`);
        
        // Wait for continuous spin to build up
        await new Promise(resolve => setTimeout(resolve, 1500));
        
        // Calculate exact landing position from server data
        const targetAngle = serverDecision.sector_center || (serverDecision.sector_index * (360 / this.segments.length) + (360 / this.segments.length / 2));
        const finalPosition = 360 - targetAngle;
        
        // Add exciting spins (8-12 total)
        const totalSpins = 8 + Math.random() * 4;
        const finalRotation = (totalSpins * 360) + (finalPosition % 360);
        
        dlog(`📐 Server sector center: ${targetAngle}°`);
        dlog(`🎡 Final rotation: ${finalRotation}° (${totalSpins.toFixed(1)} spins)`);
        
        // Smooth deceleration to exact server position
        this.wheelInner.style.transition = 'transform 4s cubic-bezier(0.23, 1, 0.32, 1)';
        this.wheelInner.style.transform = `rotate(${finalRotation}deg)`;
        
        // Update current rotation
        this.currentRotation = finalRotation % 360;
        
        // Wait for animation completion
        return new Promise(resolve => {
            setTimeout(() => {
                this.stopTickingSound();
                dlog('🎡 Wheel landed on server-selected sector');
                resolve();
            }, 4000);
        });
    }

    // === PHASE 4: DISPLAY SERVER MESSAGE ===
    displayServerAuthorizedResult(serverDecision) {
        dlog('🎉 Displaying server-authorized result...');
        
        // Verify the wheel actually landed on the correct sector
        const actualSector = this.getCurrentSector();
        const expectedSector = serverDecision.sector_index;
        
        dlog(`🎯 Landing verification:`);
        dlog(`   Expected sector: ${expectedSector}`);
        dlog(`   Actual sector: ${actualSector}`);
        dlog(`   Match: ${actualSector === expectedSector ? '✅ PERFECT' : '❌ MISMATCH'}`);
        
        // === DEBUG: LOG EXACTLY WHAT WILL BE DISPLAYED ===
        const prizeToDisplay = {
            ...serverDecision.prize,
            serverMessage: serverDecision.message,
            reservationId: serverDecision.reservation_id,
            isServerAuthorized: true
        };
        
        dlog('🔍 DEBUG: Prize being sent to popup');
        dlog(`   Prize ID: ${prizeToDisplay.id}`);
        dlog(`   Prize name: ${prizeToDisplay.name}`);
        dlog(`   Prize emoji: ${prizeToDisplay.emoji}`);
        dlog(`   Prize budget tier: ${prizeToDisplay.budget_tier}`);
        dlog(`   Server message: ${prizeToDisplay.serverMessage}`);
        dlog(`   Is server authorized: ${prizeToDisplay.isServerAuthorized}`);
        
        // Display the server-authorized prize (regardless of visual landing)
        this.showCelebration(prizeToDisplay);
    }

    // === PHASE 5: CLIENT CONFIRMS RECEIPT, SERVER FINALIZES ===
    async confirmReceiptAndFinalize(serverDecision, idempotencyKey) {
        dlog('✅ Confirming receipt and requesting finalization...');
        
        const response = await fetch(`${this.apiBaseUrl}/spin/finalize`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Idempotency-Key': idempotencyKey
            },
            body: JSON.stringify({
                user_id: this.getUserId(),
                reservation_id: serverDecision.reservation_id,
                client_confirmation: {
                    received_at: Date.now(),
                    prize_id: serverDecision.prize.id,
                    sector_index: serverDecision.sector_index
                },
                signature_verification: 'confirmed'
            })
        });

        const data = await response.json();
        if (!data.success) {
            throw new Error(data.error || 'Prize finalization failed');
        }

        dlog('🏆 Prize finalized by server:');
        dlog(`   Award ID: ${data.award_id}`);
        dlog(`   Status: ${data.status}`);
        dlog(`   Inventory updated: ${data.inventory_updated}`);
        
        return data;
    }

    // === UTILITY: VERIFY SERVER SIGNATURE ===
    verifyServerSignature(serverResponse) {
        // In production, implement proper HMAC/JWT verification
        // For now, just check that signature exists and has reasonable format
        const signature = serverResponse.signature;
        if (!signature || signature.length < 32) {
            dwarn('⚠️ Server signature missing or too short');
            return false;
        }
        
        // TODO: Implement actual cryptographic verification
        // const expectedSignature = hmac_sha256(serverResponse.payload, SECRET_KEY);
        // return signature === expectedSignature;
        
        dlog('✅ Server signature verified (mock implementation)');
        return true;
    }

    // === UTILITY: GET CURRENT SECTOR ===
    getCurrentSector() {
        const currentRotation = this.currentRotation % 360;
        const segmentAngle = 360 / this.segments.length;
        const sectorAtPointer = (360 - currentRotation) % 360;
        return Math.floor(sectorAtPointer / segmentAngle);
    }

    // === UTILITY: GET SESSION ID ===
    getSessionId() {
        if (!this.sessionId) {
            this.sessionId = 'session_' + Date.now() + '_' + Math.random().toString(36).substring(2, 15);
        }
        return this.sessionId;
    }

    // === UTILITY: GET ACTUAL CSS ROTATION ===
    getActualCSSRotation() {
        try {
            const computedTransform = window.getComputedStyle(this.wheelInner).transform;
            if (computedTransform && computedTransform !== 'none') {
                const matrix = computedTransform.match(/matrix\(([^)]+)\)/);
                if (matrix) {
                    const values = matrix[1].split(',').map(parseFloat);
                    const actualRotation = Math.atan2(values[1], values[0]) * (180 / Math.PI);
                    // Normalize to 0-360 range
                    return ((actualRotation % 360) + 360) % 360;
                }
            }
            return null;
        } catch (error) {
            dwarn('Could not read CSS rotation:', error);
            return null;
        }
    }

    // === STEP 1: START WHEEL SPINNING IMMEDIATELY ===
    startWheelSpinning() {
        dlog('🎡 Starting immediate wheel rotation...');
        
        // Start ticking sound
        this.startTickingSound();
        
        // Start with a continuous spinning animation (no end point yet)
        this.wheelInner.style.transition = 'none';
        this.wheelInner.style.transform = `rotate(${this.currentRotation}deg)`;
        
        // Force reflow
        this.wheelInner.offsetHeight;
        
        // Start continuous spinning - we'll adjust the endpoint later
        const initialSpins = 3; // Start with 3 full rotations
        const initialRotation = this.currentRotation + (initialSpins * 360);
        
        this.wheelInner.style.transition = 'transform 2s linear';
        this.wheelInner.style.transform = `rotate(${initialRotation}deg)`;
        
        dlog(`🎡 Wheel spinning continuously from ${this.currentRotation}° to ${initialRotation}°`);
        
        return {
            startTime: Date.now(),
            initialRotation: initialRotation
        };
    }

    // === STEP 3: FIND WHERE WINNING PRIZE IS LOCATED ON WHEEL ===
    findPrizeLocationOnWheel(winningPrize) {
        dlog(`🎯 Finding location of ${winningPrize.name} (ID: ${winningPrize.id}) on wheel...`);
        
        // Find which segment contains this prize
        const targetSegmentIndex = this.segments.findIndex(segment => segment.id === winningPrize.id);
        
        if (targetSegmentIndex === -1) {
            throw new Error(`Prize ${winningPrize.name} (ID: ${winningPrize.id}) not found on wheel!`);
        }
        
        const segmentAngle = 360 / this.segments.length;
        const segmentCenterAngle = targetSegmentIndex * segmentAngle + (segmentAngle / 2);
        
        dlog(`✅ Found prize at segment ${targetSegmentIndex}, center angle: ${segmentCenterAngle}°`);
        
        return {
            segmentIndex: targetSegmentIndex,
            centerAngle: segmentCenterAngle,
            prize: winningPrize
        };
    }

    // === STEP 4: ADJUST WHEEL TO LAND ON WINNING ITEM ===
    async adjustWheelToLandOnPrize(targetLocation, spinPromise) {
        dlog(`🔄 Adjusting wheel to land on ${targetLocation.prize.name}...`);
        
        // Wait a moment for the initial spin to get going
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        // Calculate the exact final position needed
        const targetFinalRotation = 360 - targetLocation.centerAngle;
        const normalizedTarget = targetFinalRotation % 360;
        
        // Add many more spins for excitement (total 8-12 spins)
        const totalSpins = 8 + Math.random() * 4;
        const finalRotation = (totalSpins * 360) + normalizedTarget;
        
        dlog(`🎯 Target segment: ${targetLocation.segmentIndex}`);
        dlog(`📐 Segment center: ${targetLocation.centerAngle}°`);
        dlog(`🎡 Final rotation: ${finalRotation}° (${totalSpins.toFixed(1)} total spins)`);
        
        // Smoothly transition to the exact landing position
        this.wheelInner.style.transition = 'transform 4s cubic-bezier(0.23, 1, 0.32, 1)';
        this.wheelInner.style.transform = `rotate(${finalRotation}deg)`;
        
        // Update current rotation for next spin
        this.currentRotation = finalRotation % 360;
        
        // Wait for the wheel to finish spinning
        return new Promise(resolve => {
            setTimeout(() => {
                this.stopTickingSound();
                dlog('🎡 Wheel finished spinning');
                resolve();
            }, 4000);
        });
    }

    // === STEP 5: VERIFY PERFECT LANDING ===
    verifyFinalLanding(expectedPrize, targetLocation) {
        dlog('✅ Verifying final landing position...');
        
        const finalRotation = this.currentRotation;
        const segmentAngle = 360 / this.segments.length;
        
        // Calculate which segment is at the pointer
        const wheelPosition = finalRotation % 360;
        const segmentAtPointer = (360 - wheelPosition) % 360;
        const actualSegment = Math.floor(segmentAtPointer / segmentAngle);
        const boundaryAdjusted = actualSegment >= this.segments.length ? 0 : actualSegment;
        
        const landedPrize = this.segments[boundaryAdjusted];
        
        dlog(`🎯 Landing Verification:`);
        dlog(`   Expected: Segment ${targetLocation.segmentIndex} (${expectedPrize.name})`);
        dlog(`   Actual: Segment ${boundaryAdjusted} (${landedPrize ? landedPrize.name : 'Unknown'})`);
        dlog(`   Final rotation: ${finalRotation}°`);
        
        const isPerfect = boundaryAdjusted === targetLocation.segmentIndex;
        dlog(`   Result: ${isPerfect ? '✅ PERFECT LANDING' : '❌ MISSED TARGET'}`);
        
        return {
            isPerfect: isPerfect,
            expectedSegment: targetLocation.segmentIndex,
            actualSegment: boundaryAdjusted,
            landedPrize: landedPrize
        };
    }

    // === STEP 1: BACKEND DETERMINES AVAILABLE PRIZE ===
    async getBackendSelectedPrize() {
        dlog('📡 Requesting available prize from backend...');
        
        const response = await fetchWithTimeout(`${this.apiBaseUrl}/pre-spin`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                user_id: this.getUserId()
            })
        });

        const data = await response.json();
        if (!data.success) {
            throw new Error(data.error || 'Backend prize selection failed');
        }

        const prize = data.selected_prize;
        const targetSegment = data.target_segment_index;
        
        dlog(`✅ Backend selected: ${prize.name} (ID: ${prize.id}) → Segment ${targetSegment}`);
        
        return {
            prize: prize,
            targetSegment: targetSegment,
            totalSegments: data.total_segments
        };
    }

    // === STEP 2: FRONTEND CALCULATES WHEEL ROTATION ===
    async calculateWheelRotation(availablePrize) {
        dlog('🔄 Calculating precise wheel rotation...');
        
        const targetSegment = availablePrize.targetSegment;
        const prize = availablePrize.prize;
        
        // Verify mapping between backend selection and wheel display
        const wheelPrizeAtSegment = this.segments[targetSegment];
        dlog(`🔍 Verifying: Wheel segment ${targetSegment} ID=${wheelPrizeAtSegment?.id}, Backend prize ID=${prize.id}`);
        
        if (!wheelPrizeAtSegment || wheelPrizeAtSegment.id !== prize.id) {
            console.error(`❌ Mapping mismatch! Wheel segments:`, this.segments.map(s => ({idx: s.index, id: s.id, name: s.name})));
            throw new Error(`Mapping error: Backend prize ${prize.id} doesn't match wheel segment ${targetSegment} (segment has ID: ${wheelPrizeAtSegment?.id})`);
        }
        
        dlog(`✅ Mapping verified: Segment ${targetSegment} = ${wheelPrizeAtSegment.name}`);
        
        // Calculate exact rotation needed
        const totalRotation = this.calculateExactRotation(targetSegment);
        
        return {
            targetSegment: targetSegment,
            totalRotation: totalRotation,
            prize: prize
        };
    }

    // === STEP 4: VERIFY ALIGNMENT ===
    verifyWheelAlignment(availablePrize, targetSegment) {
        dlog('✅ Verifying wheel landed correctly...');
        
        const finalRotation = this.currentRotation;
        const segmentAngle = 360 / this.segments.length;
        
        // Calculate which segment is at the pointer (top of wheel)
        // The pointer is at 0° (top). We need to find which segment is currently at 0°
        // Since the wheel rotates clockwise, we need to account for the rotation
        const wheelPosition = finalRotation % 360;
        
        // ORIGINAL WORKING LOGIC: Calculate which segment is at the pointer
        const segmentAtPointer = (360 - wheelPosition) % 360;
        const actualLandedSegment = Math.floor(segmentAtPointer / segmentAngle);
        const boundaryAdjustedSegment = actualLandedSegment >= this.segments.length ? 0 : actualLandedSegment;
        
        const landedPrize = this.segments[boundaryAdjustedSegment];
        
        dlog(`🎯 Alignment Check:`);
        dlog(`   Expected: Segment ${targetSegment} (${availablePrize.prize.name})`);
        dlog(`   Actual: Segment ${boundaryAdjustedSegment} (${landedPrize ? landedPrize.name : 'Unknown'})`);
        dlog(`   Final rotation: ${finalRotation}°`);
        dlog(`   Wheel position: ${wheelPosition}°`);
        dlog(`   Segment angle: ${segmentAngle}°`);
        dlog(`   Segment at pointer: ${segmentAtPointer}°`);
        
        const isAligned = boundaryAdjustedSegment === targetSegment;
        dlog(`   Alignment: ${isAligned ? '✅ PERFECT' : '❌ MISALIGNED'}`);
        
        return {
            isAligned: isAligned,
            expectedSegment: targetSegment,
            actualSegment: boundaryAdjustedSegment,
            landedPrize: landedPrize
        };
    }

    // === STEP 5: BACKEND CONFIRMS AND AWARDS PRIZE ===
    async confirmPrizeWithBackend(availablePrize, rotationData) {
        dlog('🏆 Confirming prize award with backend...');
        
        const response = await fetchWithTimeout(`${this.apiBaseUrl}/spin`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                user_id: this.getUserId(),
                selected_prize_id: availablePrize.prize.id,
                target_segment_index: rotationData.targetSegment,
                final_rotation: rotationData.totalRotation
            })
        });

        const data = await response.json();
        if (!data.success) {
            throw new Error(data.error || 'Prize confirmation failed');
        }

        const awardedPrize = data.prize;
        dlog(`✅ Prize confirmed and awarded: ${awardedPrize.name}`);
        
        // Add prize to daily log
        this.addPrizeToLog(awardedPrize);
        
        // Verify backend didn't change the prize
        if (awardedPrize.id !== availablePrize.prize.id) {
            dwarn('⚠️ Backend changed the prize!');
            dwarn(`   Originally selected: ${availablePrize.prize.name}`);
            dwarn(`   Actually awarded: ${awardedPrize.name}`);
        }
        
        return awardedPrize;
    }

    showCelebration(prize) {
        dlog('🎉 Showing prize modal for:', prize.name);
        
        // 🎉 ENHANCED CELEBRATION SEQUENCE
        this.startCelebrationSequence(prize);
        
        // === DEBUG: LOG POPUP DISPLAY DETAILS ===
        dlog('🔍 DEBUG: Popup display details');
        dlog(`   Received prize object:`, prize);
        dlog(`   Prize ID: ${prize.id}`);
        dlog(`   Prize name: ${prize.name}`);
        dlog(`   Prize emoji: ${prize.emoji}`);
        dlog(`   Prize budget tier: ${prize.budget_tier}`);

        const prizeEmoji = document.getElementById('prizeEmoji');
        const prizeName = document.getElementById('prizeName');
        const prizeDisplay = document.getElementById('prizeDisplay');

        dlog('🔍 DEBUG: Setting DOM elements');
        dlog(`   Setting emoji to: ${prize.emoji || '🎁'}`);
        dlog(`   Setting name to: ${prize.name}`);

        if (prizeEmoji) {
            // Same flat icon as the wheel slice (combo emojis for legacy combo
            // prizes); size comes from CSS
            const comboEmoji = this.getComboEmojiDisplay(prize.name);
            prizeEmoji.textContent = comboEmoji || this.getPrizeIcon(prize.name);
        }
        if (prizeName) prizeName.textContent = prize.name;

        if (prizeDisplay) {
            prizeDisplay.innerHTML = '';
            const description = document.createElement('p');
            description.textContent = prize.description || `Congratulations on winning ${prize.name}!`;
            description.style.fontSize = '1.1rem';
            description.style.color = 'var(--text-secondary)';
            prizeDisplay.appendChild(description);
        }

        this.modalOverlay.classList.add('show');
    }
    
    // 🎉 ENHANCED CELEBRATION SYSTEM
    startCelebrationSequence(prize) {
        dlog('🎉 Starting celebration sequence for:', prize.name, 'Budget tier:', prize.budget_tier);
        
        // Stop any ongoing sounds first
        this.stopTickingSound();
        
        // 1. Play celebration sound with proper timing (1-2 seconds)
        setTimeout(() => {
            this.playCelebrationSound(prize.category);
        }, 300); // Small delay after wheel stops
        
        // 2. Start confetti animation
        setTimeout(() => {
            this.showConfetti(prize.category);
        }, 500);
        
        // 3. Add celebration effects to modal
        setTimeout(() => {
            this.addModalCelebrationEffects(prize.category);
        }, 200);
    }
    
    playCelebrationSound(category) {
        if (!this.soundEnabled) {
            dlog('🔇 Sound disabled, skipping celebration sound');
            return;
        }
        
        try {
            let soundToPlay;
            let duration = 4000; // 4 seconds default
            
            // Choose sound and duration based on prize category
            if (category === 'rare' || category === 'ultra_rare') {
                soundToPlay = this.audioElements.rareWinSound;
                duration = 5000; // 5 seconds for rare prizes - more celebration!
                dlog('🎵 Playing RARE celebration sound for', category);
            } else {
                soundToPlay = this.audioElements.winSound;
                duration = 4000; // 4 seconds for common prizes
                dlog('🎵 Playing COMMON celebration sound for', category);
            }
            
            if (soundToPlay) {
                // Reset and play
                soundToPlay.currentTime = 0;
                soundToPlay.volume = 0.8; // Slightly louder for celebration
                
                const playPromise = soundToPlay.play();
                
                if (playPromise !== undefined) {
                    playPromise
                        .then(() => {
                            dlog('🎵 Celebration sound started successfully');
                            
                            // Stop sound after specified duration
                            setTimeout(() => {
                                if (!soundToPlay.paused) {
                                    soundToPlay.pause();
                                    soundToPlay.currentTime = 0;
                                    dlog('🔇 Celebration sound stopped after', duration + 'ms');
                                }
                            }, duration);
                        })
                        .catch(error => {
                            dwarn('⚠️ Failed to play celebration sound:', error);
                            // Fallback: try to enable audio context
                            if (this.audioContext && this.audioContext.state === 'suspended') {
                                this.audioContext.resume().then(() => {
                                    dlog('🔊 Audio context resumed, retrying sound...');
                                    soundToPlay.play().catch(e => dwarn('⚠️ Retry failed:', e));
                                });
                            }
                        });
                }
            } else {
                dwarn('⚠️ No sound element available for prize rarity:', category);
            }
        } catch (error) {
            dwarn('⚠️ Error playing celebration sound:', error);
        }
    }
    
    showConfetti(category) {
        dlog('🎊 Starting confetti animation for:', category);
        
        // Create confetti container
        const confettiContainer = document.createElement('div');
        confettiContainer.className = 'confetti-container';
        confettiContainer.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            pointer-events: none;
            z-index: 10000;
            overflow: hidden;
        `;
        
        document.body.appendChild(confettiContainer);
        
        // Determine confetti intensity based on category
        const confettiCount = category === 'rare' || category === 'ultra_rare' ? 50 : 30;
        const isMaterial = document.documentElement.dataset.designMode === 'material';
        const colors = isMaterial
            // Google's own four brand colours, same order as the "G" logo
            ? ['#4285F4', '#EA4335', '#FBBC04', '#34A853', '#FFFFFF']
            : category === 'rare' || category === 'ultra_rare'
                ? ['#FFD36B', '#F5B83D', '#FF2B86', '#FF4FA3', '#E50065', '#FFFFFF', '#FFC2DD', '#FF8CC0']
                : ['#FFD36B', '#FF2B86', '#FF4FA3', '#E50065', '#FFFFFF'];
        
        // Create confetti pieces
        for (let i = 0; i < confettiCount; i++) {
            setTimeout(() => {
                this.createConfettiPiece(confettiContainer, colors);
            }, i * 50); // Stagger creation
        }
        
        // Remove confetti container after animation (match celebration duration)
        const confettiDuration = category === 'rare' || category === 'ultra_rare' ? 6000 : 5000;
        setTimeout(() => {
            if (confettiContainer.parentNode) {
                confettiContainer.parentNode.removeChild(confettiContainer);
                dlog('🧹 Confetti cleaned up');
            }
        }, confettiDuration);
    }
    
    createConfettiPiece(container, colors) {
        const confetti = document.createElement('div');
        const color = colors[Math.floor(Math.random() * colors.length)];
        const size = Math.random() * 8 + 4; // 4-12px
        const startX = Math.random() * window.innerWidth;
        const endX = startX + (Math.random() - 0.5) * 200; // Drift sideways
        const duration = Math.random() * 3000 + 3000; // 3-6 seconds (longer fall)
        const delay = Math.random() * 1000; // 0-1000ms delay (more staggered)
        
        confetti.style.cssText = `
            position: absolute;
            width: ${size}px;
            height: ${size}px;
            background: ${color};
            border-radius: ${Math.random() > 0.5 ? '50%' : '0'};
            left: ${startX}px;
            top: -20px;
            transform: rotate(${Math.random() * 360}deg);
            animation: confettiFall ${duration}ms linear ${delay}ms forwards;
        `;
        
        // Add CSS animation if not already added
        if (!document.getElementById('confetti-styles')) {
            const style = document.createElement('style');
            style.id = 'confetti-styles';
            style.textContent = `
                @keyframes confettiFall {
                    0% {
                        transform: translateY(-20px) rotate(0deg);
                        opacity: 1;
                    }
                    100% {
                        transform: translateY(${window.innerHeight + 20}px) translateX(${endX - startX}px) rotate(720deg);
                        opacity: 0;
                    }
                }
            `;
            document.head.appendChild(style);
        }
        
        container.appendChild(confetti);
    }
    
    addModalCelebrationEffects(category) {
        if (!this.modalOverlay) return;
        
        // Add celebration class to modal
        const celebrationClass = category === 'rare' || category === 'ultra_rare' ? 'rare-celebration' : 'common-celebration';
        this.modalOverlay.classList.add('celebrating', celebrationClass);
        
        // Add enhanced pulsing effect to prize emoji
        const prizeEmoji = document.getElementById('prizeEmoji');
        if (prizeEmoji) {
            const pulseCount = category === 'rare' || category === 'ultra_rare' ? 8 : 6;
            prizeEmoji.style.animation = `celebrationPulse 0.8s ease-in-out ${pulseCount}`;
        }
        
        // Add celebration styles if not already added
        if (!document.getElementById('celebration-styles')) {
            const style = document.createElement('style');
            style.id = 'celebration-styles';
            style.textContent = `
                @keyframes celebrationPulse {
                    0%, 100% { transform: scale(1); filter: brightness(1); }
                    25% { transform: scale(1.08); filter: brightness(1.2); }
                    50% { transform: scale(1.15); filter: brightness(1.4); }
                    75% { transform: scale(1.08); filter: brightness(1.2); }
                }
                
                /* Prevent emoji overflow and scrollbars */
                .modal-overlay .modal-content,
                .modal-overlay .modal {
                    overflow: hidden !important;
                    box-sizing: border-box;
                }
                
                .modal-overlay .prize-emoji {
                    display: inline-block;
                    transform-origin: center center;
                    will-change: transform, filter;
                    margin: 0.5rem 0 !important;
                    line-height: 1 !important;
                }
                
                /* Ensure modal has enough padding to accommodate scaling */
                .modal-overlay.celebrating .modal {
                    padding: 2.5rem 2rem !important;
                }
                
                .modal-overlay.celebrating .modal-content {
                    padding: 1.5rem !important;
                }
                
                .modal-overlay.celebrating {
                    animation: modalCelebration 1.2s cubic-bezier(0.34, 1.56, 0.64, 1);
                }
                
                .modal-overlay.rare-celebration .modal-content {
                    box-shadow: 
                        0 0 30px rgba(255, 215, 0, 0.8), 
                        0 0 60px rgba(255, 215, 0, 0.6),
                        0 0 90px rgba(255, 215, 0, 0.4);
                    border: 3px solid #FFD700;
                    animation: rareCelebrationGlow 2s ease-in-out infinite alternate;
                }
                
                .modal-overlay.common-celebration .modal-content {
                    box-shadow: 
                        0 0 20px rgba(76, 175, 80, 0.7),
                        0 0 40px rgba(76, 175, 80, 0.5);
                    border: 2px solid #4CAF50;
                    animation: commonCelebrationGlow 2s ease-in-out infinite alternate;
                }
                
                @keyframes modalCelebration {
                    0% { 
                        transform: scale(0.8) rotate(-3deg); 
                        opacity: 0; 
                        filter: blur(2px);
                    }
                    30% { 
                        transform: scale(1.05) rotate(1deg); 
                        opacity: 0.8; 
                        filter: blur(1px);
                    }
                    60% { 
                        transform: scale(0.98) rotate(-0.5deg); 
                        opacity: 1; 
                        filter: blur(0px);
                    }
                    100% { 
                        transform: scale(1) rotate(0deg); 
                        opacity: 1; 
                        filter: blur(0px);
                    }
                }
                
                @keyframes rareCelebrationGlow {
                    0% { 
                        box-shadow: 
                            0 0 30px rgba(255, 215, 0, 0.8), 
                            0 0 60px rgba(255, 215, 0, 0.6),
                            0 0 90px rgba(255, 215, 0, 0.4);
                    }
                    100% { 
                        box-shadow: 
                            0 0 40px rgba(255, 215, 0, 1), 
                            0 0 80px rgba(255, 215, 0, 0.8),
                            0 0 120px rgba(255, 215, 0, 0.6);
                    }
                }
                
                @keyframes commonCelebrationGlow {
                    0% { 
                        box-shadow: 
                            0 0 20px rgba(76, 175, 80, 0.7),
                            0 0 40px rgba(76, 175, 80, 0.5);
                    }
                    100% { 
                        box-shadow: 
                            0 0 30px rgba(76, 175, 80, 0.9),
                            0 0 60px rgba(76, 175, 80, 0.7);
                    }
                }
            `;
            document.head.appendChild(style);
        }
        
        // Remove celebration effects after animation (match sound duration)
        const cleanupDelay = category === 'rare' || category === 'ultra_rare' ? 6000 : 5000;
        setTimeout(() => {
            this.modalOverlay.classList.remove('celebrating', 'rare-celebration', 'common-celebration');
            if (prizeEmoji) {
                prizeEmoji.style.animation = '';
            }
        }, cleanupDelay);
        
        dlog('✨ Modal celebration effects added for:', category);
    }

    closeModal() {
        if (this.modalOverlay) {
            this.modalOverlay.classList.remove('show', 'celebrating', 'rare-celebration', 'common-celebration');
        }
    }

    showLoading() {
        if (this.loadingOverlay) {
            this.loadingOverlay.classList.add('show');
        }
    }

    hideLoading() {
        if (this.loadingOverlay) {
            this.loadingOverlay.classList.remove('show');
        }
    }

    showError(message) {
        const existingError = document.querySelector('.error-message');
        if (existingError) {
            existingError.remove();
        }

        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = message;

        const wheelSection = document.querySelector('.wheel-container');
        if (wheelSection) {
            wheelSection.insertAdjacentElement('afterend', errorDiv);
        }

        setTimeout(() => {
            if (errorDiv.parentNode) {
                errorDiv.remove();
            }
        }, 5000);
    }
    
    // No daily limit error handling needed - backend filters out prizes that have reached their daily limit

    getUserId() {
        let userId = localStorage.getItem('picker_wheel_user_id');
        if (!userId) {
            userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
            localStorage.setItem('picker_wheel_user_id', userId);
        }
        return userId;
    }
    
    // 📋 DAILY PRIZES LOG SYSTEM
    initializeDailyPrizesLog() {
        dlog('📋 Initializing daily prizes log...');
        
        // Get DOM elements
        this.refreshLogBtn = document.getElementById('refreshLogBtn');
        this.clearLogBtn = document.getElementById('clearLogBtn');
        this.dailyPrizesTableBody = document.getElementById('dailyPrizesTableBody');
        this.totalPrizesCount = document.getElementById('totalPrizesCount');
        this.lastUpdated = document.getElementById('lastUpdated');
        
        // Add event listeners
        if (this.refreshLogBtn) {
            this.refreshLogBtn.addEventListener('click', () => this.refreshDailyPrizesLog());
        }
        
        if (this.clearLogBtn) {
            this.clearLogBtn.addEventListener('click', () => this.clearLogDisplay());
        }
        
        // Load initial data
        this.refreshDailyPrizesLog();
        
        // Auto-refresh every 30 seconds
        setInterval(() => {
            if (!this.logDisplayHidden) {
                this.refreshDailyPrizesLog();
            }
        }, 30000);
        
        dlog('✅ Daily prizes log initialized');
    }
    
    async refreshDailyPrizesLog() {
        try {
            dlog('🔄 Refreshing daily prizes log...');
            
            const response = await fetch('/api/daily-prizes-log');
            const data = await response.json();
            
            if (data.success) {
                this.dailyPrizesLog = data.prizes_won;
                this.updateDailyPrizesDisplay();
                this.updateLogStats(data.total_count);
                dlog(`✅ Loaded ${data.total_count} prize entries`);
            } else {
                dwarn('⚠️ Failed to load daily prizes log:', data.error);
            }
        } catch (error) {
            console.error('❌ Error refreshing daily prizes log:', error);
        }
    }
    
    updateDailyPrizesDisplay() {
        if (!this.dailyPrizesTableBody) return;
        
        // Clear existing rows
        this.dailyPrizesTableBody.innerHTML = '';
        
        if (this.dailyPrizesLog.length === 0) {
            // Show no data message
            const noDataRow = document.createElement('tr');
            noDataRow.className = 'no-data-row';
            noDataRow.innerHTML = `
                <td colspan="3">No prizes won today yet. Spin the wheel to get started!</td>
            `;
            this.dailyPrizesTableBody.appendChild(noDataRow);
            return;
        }
        
        // Add prize rows (category intentionally not shown)
        this.dailyPrizesLog.forEach(prize => {
            const row = document.createElement('tr');

            const prizeCell = document.createElement('td');
            const prizeWrap = document.createElement('div');
            prizeWrap.className = 'prize-cell';
            const icon = document.createElement('span');
            const comboEmoji = this.getComboEmojiDisplay(prize.name);
            icon.className = comboEmoji ? 'log-prize-icon' : 'log-prize-icon material-symbol';
            icon.textContent = comboEmoji || this.getPrizeIcon(prize.name);
            const name = document.createElement('span');
            name.className = 'log-prize-name';
            name.textContent = prize.name;
            prizeWrap.append(icon, name);
            prizeCell.appendChild(prizeWrap);

            const timeCell = document.createElement('td');
            timeCell.className = 'time-cell';
            timeCell.textContent = prize.formatted_time;

            const userCell = document.createElement('td');
            userCell.className = 'user-cell';
            userCell.textContent = prize.user_identifier;

            row.append(prizeCell, timeCell, userCell);
            this.dailyPrizesTableBody.appendChild(row);
        });
    }
    
    updateLogStats(totalCount) {
        if (this.totalPrizesCount) {
            this.totalPrizesCount.textContent = totalCount;
        }
        
        if (this.lastUpdated) {
            const now = new Date();
            this.lastUpdated.textContent = now.toLocaleTimeString();
        }
    }
    
    clearLogDisplay() {
        dlog('🗑️ Clearing log display (UI only)...');
        
        // Clear the display but keep the actual data
        this.logDisplayHidden = true;
        
        if (this.dailyPrizesTableBody) {
            this.dailyPrizesTableBody.innerHTML = `
                <tr class="no-data-row">
                    <td colspan="3">Log display cleared. Click "Refresh" to reload data.</td>
                </tr>
            `;
        }
        
        if (this.totalPrizesCount) {
            this.totalPrizesCount.textContent = '0 (hidden)';
        }
        
        if (this.lastUpdated) {
            this.lastUpdated.textContent = 'Display cleared';
        }
        
        // Show refresh button prominently
        if (this.refreshLogBtn) {
            this.refreshLogBtn.style.background = 'rgba(76, 175, 80, 0.3)';
            this.refreshLogBtn.style.border = '2px solid #4CAF50';
            
            // Reset button style after 3 seconds
            setTimeout(() => {
                this.refreshLogBtn.style.background = '';
                this.refreshLogBtn.style.border = '';
            }, 3000);
        }
        
        // Re-enable auto-refresh on next refresh click
        this.logDisplayHidden = false;
    }
    
    // Add prize to log when won (called after successful spin)
    addPrizeToLog(prize) {
        const now = new Date();
        const logEntry = {
            prize_id: prize.id,
            name: prize.name,
            user_identifier: 'You',
            formatted_time: now.toLocaleTimeString(),
            category: prize.category || prize.category_name || 'common',  // Handle both naming conventions
            emoji: prize.emoji
        };
        
        // Add to beginning of array (most recent first)
        this.dailyPrizesLog.unshift(logEntry);
        
        // Update display if not hidden
        if (!this.logDisplayHidden) {
            this.updateDailyPrizesDisplay();
            this.updateLogStats(this.dailyPrizesLog.length);
        }
        
        dlog('📋 Added prize to log:', prize.name);
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    dlog('🚀 DOM loaded, initializing PickerWheel UI...');
    window.pickerWheelUI = new PickerWheelUI();
});

// Version information for cache validation
const WHEEL_VERSION = '11.3_20250922';
const BUILD_DATE = '2025-09-22';

dlog('📱 PickerWheel UI v' + WHEEL_VERSION + ' loaded successfully!');
dlog('🗓 Build date: ' + BUILD_DATE);

// Clear browser cache for API requests
if ('caches' in window) {
    caches.keys().then(cacheNames => {
        cacheNames.forEach(cacheName => {
            if (cacheName.includes('wheel') || cacheName.includes('prize') || cacheName.includes('spin')) {
                dlog('🧹 Clearing cache:', cacheName);
                caches.delete(cacheName);
            }
        });
    });
}

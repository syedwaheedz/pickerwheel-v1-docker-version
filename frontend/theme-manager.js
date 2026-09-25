/**
 * ThemeManager - applies a running special event's theme on top of Neon.
 *
 * The page has exactly two built-in designs, both defined in style.css:
 * Neon (default) and Material (black & white), switched by the
 * data-design-mode attribute. The only server-side theme is one attached to
 * a currently active special event (from /api/config); it recolours the
 * Neon design while the event runs. Material ignores event colours so it
 * always stays black & white.
 */

class ThemeManager {
    constructor() {
        this.apiBaseUrl = '/api';
        this.activeTheme = null;   // active event's theme, or null
        this.activeEvent = null;
    }

    /**
     * Load the active event (and its theme, if any) from the backend
     */
    async loadConfig() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/config`, { cache: 'no-cache' });
            const data = await response.json();

            if (data.success) {
                this.activeTheme = data.theme || null;
                this.activeEvent = data.event;
                if (this.activeTheme) {
                    console.log('🎨 Applying event theme:', data.event?.name);
                }
                return data;
            }
            console.warn('⚠️ Failed to load config');
        } catch (error) {
            console.error('❌ Error loading config:', error);
        }
        this.activeTheme = null;
        return null;
    }

    /**
     * Apply the event theme - or, with no event theme / in Material mode,
     * clear any inline overrides so the built-in CSS design shows
     */
    applyTheme() {
        this.applyBackground();
        this.applyHeader();
        this.applyFloatingElements();
    }

    /**
     * Event themes only apply to Neon; Material always uses its own CSS
     */
    get eventThemeApplies() {
        return !!this.activeTheme && document.documentElement.dataset.designMode !== 'material';
    }

    applyBackground() {
        const body = document.body;
        const bg = this.activeTheme?.background;

        body.style.background = '';
        body.style.backgroundColor = '';
        body.style.backgroundAttachment = '';
        body.style.backgroundSize = '';
        if (!this.eventThemeApplies || !bg) return;

        if (bg.type === 'gradient' && bg.colors) {
            const colors = bg.colors;

            if (bg.style === 'radial') {
                // Same stage layout as the built-in Neon background, driven by
                // the event's colors: base (colors[1]), ambient bloom
                // (colors[2]) and faint accent glows (colors[0]). Works for a
                // light base too.
                const base = colors[1] || colors[2] || colors[0];
                const deep = colors[2] || colors[0];
                body.style.background = `
                    radial-gradient(ellipse 70% 55% at 50% 42%, ${this.hexToRgba(deep, 0.55)} 0%, transparent 70%),
                    radial-gradient(ellipse 45% 35% at 12% 8%, ${this.hexToRgba(colors[0], 0.14)} 0%, transparent 70%),
                    radial-gradient(ellipse 45% 35% at 88% 8%, ${this.hexToRgba(colors[0], 0.12)} 0%, transparent 70%),
                    radial-gradient(ellipse 60% 30% at 50% 100%, ${this.hexToRgba(deep, 0.35)} 0%, transparent 70%),
                    ${base}
                `;
                body.style.backgroundColor = base;
            } else if (bg.style === 'linear') {
                body.style.background = `linear-gradient(180deg, ${colors.join(', ')})`;
            } else {
                body.style.background = `linear-gradient(135deg, ${colors[0]}, ${colors[1] || colors[0]})`;
            }
            body.style.backgroundAttachment = 'fixed';
        } else if (bg.type === 'solid' && bg.colors) {
            body.style.background = bg.colors[0];
        } else if (bg.type === 'image' && bg.imageUrl) {
            body.style.background = `url('${bg.imageUrl}') no-repeat center center`;
            body.style.backgroundSize = 'cover';
            body.style.backgroundAttachment = 'fixed';
        }
    }

    applyHeader() {
        const header = this.activeTheme?.header;

        // Header panel tint (translucent, so it still reads as glass)
        const topNav = document.querySelector('.top-nav');
        if (topNav) {
            topNav.style.background = this.eventThemeApplies && header?.backgroundColor
                ? `linear-gradient(135deg, ${this.hexToRgba(header.backgroundColor, 0.72)}, ${this.hexToRgba(header.gradientEnd || header.backgroundColor, 0.5)})`
                : '';
        }

        // Event title/subtitle text applies in both designs (it's content,
        // not color). Built from text nodes, never innerHTML - it comes from
        // admin-entered event data.
        if (!header) return;

        const mainTitle = document.querySelector('.main-title');
        if (mainTitle && header.title) {
            // Last word gets the accent treatment ("SPIN & " + "WIN")
            const title = header.title.trim();
            const split = title.lastIndexOf(' ');
            mainTitle.replaceChildren(
                this.span('title-lead', split > 0 ? title.slice(0, split + 1) : ''),
                this.span('title-accent', split > 0 ? title.slice(split + 1) : title)
            );
        }

        const subtitle = document.querySelector('.subtitle');
        if (subtitle && header.subtitle) {
            // Sparkles are hidden by CSS in Material
            subtitle.replaceChildren(
                this.span('sparkle', '✨ '),
                document.createTextNode(header.subtitle),
                this.span('sparkle', ' ✨')
            );
        }
    }

    applyFloatingElements() {
        const emojis = this.activeTheme?.floatingElements;
        if (!Array.isArray(emojis) || emojis.length === 0) return;

        document.querySelectorAll('.background-elements .floating-element').forEach((el, index) => {
            el.textContent = emojis[index % emojis.length];
        });
    }

    /**
     * Event wheel colors, or null to use the built-in Neon palette
     */
    getWheelColors() {
        return this.activeTheme?.wheel?.colors || null;
    }

    span(className, text) {
        const el = document.createElement('span');
        el.className = className;
        el.textContent = text;
        return el;
    }

    hexToRgba(hex, alpha = 1) {
        const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || '');
        if (!result) return `rgba(229, 0, 101, ${alpha})`;
        const [r, g, b] = result.slice(1).map(h => parseInt(h, 16));
        return `rgba(${r}, ${g}, ${b}, ${alpha})`;
    }
}

// Create global instance
window.themeManager = new ThemeManager();

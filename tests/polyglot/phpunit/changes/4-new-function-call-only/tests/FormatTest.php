<?php

declare(strict_types=1);

namespace Shop\Tests;

use PHPUnit\Framework\TestCase;
use Shop\Pricing;

final class FormatTest extends TestCase
{
    public function testFormatsAPrice(): void
    {
        Pricing::formatPrice(1250);
    }
}
